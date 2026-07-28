"""Tests del camino de carga sin PIL para el hilo productor.

`normalize_spatial` sólo necesita un ndarray RGB, pero `load_image` devolvía un
`PIL.Image` que el normalizador desenvolvía acto seguido con `np.asarray`. En las
fuentes vivas (OAK-D/RTSP) y en los frames de video eso son dos copias completas
del frame en Python —con el GIL tomado— por unidad procesada, en el hilo que
compite con la inferencia (doc 73 §9.2).

`load_image_array` es el camino directo a ndarray; estos tests fijan que el
resultado es idéntico al del camino PIL para las tres ramas de carga.
"""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
import pytest

from eovrt_media.contracts import VisualUnit
from eovrt_media.contracts.normalized_unit import PayloadFormat
from eovrt_media.models.base import ModelInputSpec
from eovrt_media.preprocessing import image_loader
from eovrt_media.preprocessing.image_loader import load_image, load_image_array
from eovrt_media.preprocessing.normalizer import normalize_spatial


def _bgr_frame(height: int = 48, width: int = 64) -> np.ndarray:
    """Frame BGR con un gradiente por canal (detecta swaps de canal)."""
    frame = np.zeros((height, width, 3), dtype=np.uint8)
    frame[:, :, 0] = np.arange(width, dtype=np.uint8)[None, :]  # B
    frame[:, :, 1] = 128
    frame[:, :, 2] = np.arange(height, dtype=np.uint8)[:, None]  # R
    return frame


def _live_unit(frame_bgr: np.ndarray) -> VisualUnit:
    h, w = frame_bgr.shape[:2]
    return VisualUnit(
        unit_id="live_0",
        source_type="image",
        width=w,
        height=h,
        pixel_data=frame_bgr,
    )


def _video_unit(tmp_path: Path, frame_bgr: np.ndarray) -> VisualUnit:
    h, w = frame_bgr.shape[:2]
    video_path = tmp_path / "sample.avi"
    writer = cv2.VideoWriter(
        str(video_path), cv2.VideoWriter_fourcc(*"MJPG"), 10.0, (w, h)
    )
    writer.write(frame_bgr)
    writer.release()
    return VisualUnit(
        unit_id="frame_000000",
        source_type="video_frame",
        frame_index=0,
        width=w,
        height=h,
        path=str(video_path),
    )


def _image_unit(tmp_path: Path, frame_bgr: np.ndarray) -> VisualUnit:
    h, w = frame_bgr.shape[:2]
    img_path = tmp_path / "sample.png"
    cv2.imwrite(str(img_path), frame_bgr)
    return VisualUnit(
        unit_id="img_0",
        source_type="image",
        width=w,
        height=h,
        path=str(img_path),
    )


class TestLoadImageArray:
    def test_returns_rgb_ndarray_for_live_frame(self):
        frame_bgr = _bgr_frame()
        result = load_image_array(_live_unit(frame_bgr))

        assert isinstance(result, np.ndarray)
        assert result.dtype == np.uint8
        assert result.shape == frame_bgr.shape
        # BGR -> RGB: el canal R del resultado es el canal 2 del BGR original.
        np.testing.assert_array_equal(result[:, :, 0], frame_bgr[:, :, 2])
        np.testing.assert_array_equal(result[:, :, 2], frame_bgr[:, :, 0])

    def test_matches_pil_path_for_live_frame(self):
        unit = _live_unit(_bgr_frame())

        np.testing.assert_array_equal(
            load_image_array(unit), np.asarray(load_image(unit))
        )

    def test_matches_pil_path_for_video_frame(self, tmp_path):
        unit = _video_unit(tmp_path, _bgr_frame())

        np.testing.assert_array_equal(
            load_image_array(unit), np.asarray(load_image(unit))
        )

    def test_matches_pil_path_for_image_file(self, tmp_path):
        unit = _image_unit(tmp_path, _bgr_frame())

        np.testing.assert_array_equal(
            load_image_array(unit), np.asarray(load_image(unit))
        )

    def test_missing_path_raises(self):
        unit = VisualUnit(unit_id="u", source_type="image", width=1, height=1)

        with pytest.raises(ValueError, match="No se especificó ruta"):
            load_image_array(unit)

    def test_video_frame_without_index_raises(self, tmp_path):
        unit = _video_unit(tmp_path, _bgr_frame())
        unit = unit.model_copy(update={"frame_index": None})

        with pytest.raises(ValueError, match="frame_index"):
            load_image_array(unit)


class TestNormalizeSpatialSkipsPil:
    def test_does_not_build_pil_image_for_live_frame(self, monkeypatch):
        """El productor no debe construir un PIL.Image para fuentes vivas.

        Falla antes del cambio: `load_image` envuelve el frame con
        `Image.fromarray` y `normalize_spatial` lo desenvuelve enseguida.
        """
        unit = _live_unit(_bgr_frame())

        def _boom(*args, **kwargs):
            raise AssertionError("normalize_spatial construyó un PIL.Image")

        monkeypatch.setattr(image_loader.Image, "fromarray", _boom)

        normalize_spatial(
            unit, ModelInputSpec(target_size=(64, 64)), PayloadFormat.UINT8_RGB
        )

    def test_does_not_build_pil_image_for_video_frame(self, tmp_path, monkeypatch):
        unit = _video_unit(tmp_path, _bgr_frame())

        def _boom(*args, **kwargs):
            raise AssertionError("normalize_spatial construyó un PIL.Image")

        monkeypatch.setattr(image_loader.Image, "fromarray", _boom)

        normalize_spatial(
            unit, ModelInputSpec(target_size=(64, 64)), PayloadFormat.UINT8_RGB
        )


class TestNormalizedPayloadUnchanged:
    """Guard de regresión: el payload normalizado no cambia con el atajo.

    Pasa antes y después del cambio — su trabajo es cazar una regresión de
    píxeles, no dirigir el diseño.
    """

    def test_live_frame_payload_matches_reference_letterbox(self):
        frame_bgr = _bgr_frame(height=48, width=64)
        unit = _live_unit(frame_bgr)
        spec = ModelInputSpec(target_size=(64, 64), resize_mode="letterbox")

        payload = normalize_spatial(unit, spec, PayloadFormat.UINT8_RGB).payload

        # Referencia calculada aparte: RGB -> letterbox 64x64 centrado.
        rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        expected = np.zeros((64, 64, 3), dtype=np.uint8)
        expected[8:56, 0:64] = rgb
        np.testing.assert_array_equal(payload, expected)
