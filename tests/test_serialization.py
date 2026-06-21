"""Round-trip de NormalizedUnit por el wire y mensajes de control."""
from __future__ import annotations

import numpy as np

from eovrt_media.contracts.normalized_unit import (
    NormalizedUnit, PayloadFormat, ResizeTransform,
)
from eovrt_media.transport.serialization import (
    REQUEST, END_MSG, HEARTBEAT,
    serialize_unit, deserialize_unit, is_control,
)


def _make_unit(fmt: PayloadFormat) -> NormalizedUnit:
    if fmt == PayloadFormat.FP32:
        payload = np.random.rand(640, 640, 3).astype(np.float32)
    else:
        payload = (np.random.rand(640, 640, 3) * 255).astype(np.uint8)
    return NormalizedUnit(
        run_id="run_x",
        unit_id="frame_000001",
        source_id="cam0",
        source_path="rtsp://cam/stream",
        frame_index=1,
        timestamp_ms=12345.6,
        orig_width=1920,
        orig_height=1080,
        payload=payload,
        payload_format=fmt,
        target_size=(640, 640),
        transform=ResizeTransform(scale_x=0.33, scale_y=0.33, pad_x=0.0, pad_y=140.0),
    )


def test_roundtrip_uint8_rgb():
    unit = _make_unit(PayloadFormat.UINT8_RGB)
    restored = deserialize_unit(serialize_unit(unit))
    assert restored.unit_id == unit.unit_id
    assert restored.run_id == unit.run_id
    assert restored.timestamp_ms == unit.timestamp_ms
    assert restored.orig_width == unit.orig_width
    assert restored.target_size == unit.target_size
    assert restored.payload_format == PayloadFormat.UINT8_RGB
    assert restored.payload.dtype == np.uint8
    assert restored.payload.shape == (640, 640, 3)
    assert np.array_equal(restored.payload, unit.payload)
    assert restored.transform.pad_y == unit.transform.pad_y


def test_roundtrip_fp32():
    unit = _make_unit(PayloadFormat.FP32)
    restored = deserialize_unit(serialize_unit(unit))
    assert restored.payload.dtype == np.float32
    assert np.allclose(restored.payload, unit.payload)


def test_control_messages_recognized():
    assert is_control(REQUEST)
    assert is_control(END_MSG)
    assert is_control(HEARTBEAT)


def test_serialized_unit_is_not_control():
    unit = _make_unit(PayloadFormat.UINT8_RGB)
    assert not is_control(serialize_unit(unit))
