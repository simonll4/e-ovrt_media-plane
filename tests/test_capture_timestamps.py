import time

import numpy as np
import pytest

from eovrt_media.contracts.normalized_unit import NormalizedUnit, PayloadFormat, ResizeTransform
from eovrt_media.contracts.visual_unit import VisualUnit
from eovrt_media.transport.serialization import deserialize_unit, serialize_unit


def _visual_unit(**overrides) -> VisualUnit:
    data = {"unit_id": "u1", "source_type": "image", "width": 64, "height": 48}
    data.update(overrides)
    return VisualUnit(**data)


def _normalized_unit(**overrides) -> NormalizedUnit:
    data = {
        "run_id": "r1",
        "unit_id": "u1",
        "source_id": "cam-1",
        "source_path": "cam-1",
        "frame_index": 0,
        "timestamp_ms": 33.3,
        "orig_width": 64,
        "orig_height": 48,
        "payload": np.zeros((8, 8, 3), dtype=np.uint8),
        "payload_format": PayloadFormat.UINT8_RGB,
        "target_size": (8, 8),
        "transform": ResizeTransform(scale_x=1.0, scale_y=1.0, pad_x=0.0, pad_y=0.0),
    }
    data.update(overrides)
    return NormalizedUnit(**data)


def test_visual_unit_stamps_capture_time_at_construction() -> None:
    before = time.monotonic_ns()
    unit = _visual_unit()
    after = time.monotonic_ns()

    assert before <= unit.capture_monotonic_ns <= after
    assert unit.capture_wallclock_ms > 0.0
    # Vocabulario cerrado; una fuente sin declararlo no miente sobre su reloj.
    assert unit.source_clock == "none"


def test_two_visual_units_have_distinct_capture_stamps() -> None:
    """Si el default_factory se evaluara una sola vez, todas las unidades
    compartirian el mismo instante de captura y el G2A seria basura."""
    first = _visual_unit(unit_id="a")
    second = _visual_unit(unit_id="b")

    assert first.capture_monotonic_ns != second.capture_monotonic_ns


def test_visual_unit_accepts_an_explicit_source_clock() -> None:
    assert _visual_unit(source_clock="wallclock").source_clock == "wallclock"


def test_normalized_unit_carries_the_capture_stamps() -> None:
    unit = _normalized_unit(capture_monotonic_ns=123, capture_wallclock_ms=456.0,
                            source_clock="media")

    assert unit.capture_monotonic_ns == 123
    assert unit.capture_wallclock_ms == 456.0
    assert unit.source_clock == "media"


def test_serialization_roundtrip_preserves_the_capture_stamps() -> None:
    """Two-node: si el header msgpack los pierde, el Nodo B no puede calcular G2A."""
    unit = _normalized_unit(capture_monotonic_ns=987654321, capture_wallclock_ms=1700.5,
                            source_clock="wallclock")

    restored = deserialize_unit(serialize_unit(unit, codec="raw"))

    assert restored.capture_monotonic_ns == 987654321
    assert restored.capture_wallclock_ms == 1700.5
    assert restored.source_clock == "wallclock"


@pytest.mark.parametrize(
    ("module", "cls_name", "expected"),
    [
        ("eovrt_media.sources.image_folder_source", "ImageFolderSource", "none"),
        ("eovrt_media.sources.video_file_source", "VideoFileSource", "media"),
        ("eovrt_media.sources.rtsp_source", "RtspSource", "wallclock"),
        ("eovrt_media.sources.oak_d_source", "OakDSource", "wallclock"),
    ],
)
def test_every_source_declares_its_clock(module, cls_name, expected) -> None:
    import importlib

    cls = getattr(importlib.import_module(module), cls_name)
    assert cls.SOURCE_CLOCK == expected


def test_normalize_spatial_preserves_the_read_instant_and_does_not_restamp() -> None:
    """El defecto mas peligroso de esta cadena: `normalize_spatial` construye un
    `NormalizedUnit` NUEVO. Si se olvidara de copiar `capture_monotonic_ns`, el
    `default_factory` lo re-estamparia EN SILENCIO con el instante de la
    normalizacion, y el G2A mediria casi cero sin que nada falle.
    """
    import time as _time

    import numpy as np

    from eovrt_media.contracts.normalized_unit import PayloadFormat
    from eovrt_media.models.base import ModelInputSpec
    from eovrt_media.preprocessing.normalizer import normalize_spatial

    unit = VisualUnit(
        unit_id="u1",
        source_type="video_frame",
        width=32,
        height=24,
        frame_index=0,
        timestamp_ms=0.0,
        source_clock="media",
        pixel_data=np.zeros((24, 32, 3), dtype=np.uint8),
    )
    read_instant = unit.capture_monotonic_ns
    read_wallclock = unit.capture_wallclock_ms
    _time.sleep(0.02)  # 20 ms: cualquier re-estampado se vuelve visible

    spec = ModelInputSpec(target_size=(16, 16))
    normalized = normalize_spatial(unit, spec, PayloadFormat.UINT8_RGB)

    assert normalized.capture_monotonic_ns == read_instant
    assert normalized.capture_wallclock_ms == read_wallclock
    assert normalized.source_clock == "media"
