"""Tests for previews rendered directly from normalized payloads."""

from __future__ import annotations

import cv2
import numpy as np
import pytest

from eovrt_media.contracts import Detection
from eovrt_media.contracts.normalized_unit import ResizeTransform
from eovrt_media.visualize import (
    annotate_payload_bgr,
    deletterbox_bgr,
    draw_detections_rgb,
)


def _detection() -> Detection:
    return Detection(
        label="person",
        confidence=0.9,
        bbox_xyxy=[1.0, 1.0, 6.0, 6.0],
        bbox_norm_xyxy=[0.1, 0.1, 0.6, 0.6],
    )


@pytest.mark.parametrize(
    ("payload", "expected_bgr"),
    [
        (np.full((10, 10, 3), [255, 0, 0], dtype=np.uint8), [0, 0, 255]),
        (np.full((10, 10, 3), [1.0, 0.0, 0.0], dtype=np.float16), [0, 0, 255]),
    ],
)
def test_draw_detections_rgb_writes_rgb_uint8_and_float_payloads(
    tmp_path, payload, expected_bgr
):
    output_path = tmp_path / "nested" / "preview.jpg"

    draw_detections_rgb(payload, [_detection()], output_path)

    rendered = cv2.imread(str(output_path))
    assert rendered is not None
    assert np.allclose(rendered[9, 9], expected_bgr, atol=5)


@pytest.mark.parametrize(
    ("payload", "expected_bgr"),
    [
        (np.full((10, 10, 3), [255, 0, 0], dtype=np.uint8), [0, 0, 255]),
        (np.full((10, 10, 3), [1.0, 0.0, 0.0], dtype=np.float16), [0, 0, 255]),
    ],
)
def test_annotate_payload_bgr_returns_bgr_array(payload, expected_bgr):
    frame = annotate_payload_bgr(payload, [_detection()])

    assert frame.dtype == np.uint8
    assert frame.shape == (10, 10, 3)
    # esquina sin anotación conserva el color convertido a BGR
    assert np.allclose(frame[9, 9], expected_bgr, atol=5)


def test_deletterbox_removes_padding_and_restores_original_aspect():
    # Frame original 200x100 (aspecto 2:1) letterboxeado a un canvas 100x100:
    # scale=0.5, contenido 100x50 centrado -> pad_y=25, pad_x=0.
    transform = ResizeTransform(scale_x=0.5, scale_y=0.5, pad_x=0.0, pad_y=25.0)
    canvas = np.zeros((100, 100, 3), dtype=np.uint8)  # barras negras
    canvas[25:75, 0:100] = (0, 0, 255)  # región de contenido (roja en BGR)

    out = deletterbox_bgr(canvas, transform, orig_width=200, orig_height=100)

    # Aspecto original recuperado (2:1), sin barras negras.
    h, w = out.shape[:2]
    assert abs((w / h) - 2.0) < 0.05
    assert out.max(axis=2).min() > 20  # ningún píxel quedó completamente negro


def test_deletterbox_maps_content_corners_to_image_corners():
    # Marca esquinas del contenido; tras des-letterboxear deben caer en las
    # esquinas de la salida (base de que bbox_norm mapee linealmente).
    transform = ResizeTransform(scale_x=0.5, scale_y=0.5, pad_x=0.0, pad_y=25.0)
    canvas = np.zeros((100, 100, 3), dtype=np.uint8)
    canvas[25:75, 0:100] = (10, 10, 10)
    canvas[25, 0] = (0, 255, 0)      # top-left del contenido
    canvas[74, 99] = (255, 0, 0)     # bottom-right del contenido

    out = deletterbox_bgr(canvas, transform, orig_width=200, orig_height=100)
    h, w = out.shape[:2]

    assert tuple(out[0, 0]) != (0, 0, 0)          # esquina superior-izq tiene contenido
    assert tuple(out[h - 1, w - 1]) != (0, 0, 0)  # esquina inferior-der tiene contenido

