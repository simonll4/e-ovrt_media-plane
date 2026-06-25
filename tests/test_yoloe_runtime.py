"""Tests for YOLOE fp16, warmup, and device resolution (Task 5)."""
from unittest.mock import MagicMock

import numpy as np
import torch
from PIL import Image

from eovrt_media.contracts.normalized_unit import (
    NormalizedUnit,
    PayloadFormat,
    ResizeTransform,
)
import eovrt_media.models.yoloe_adapter as yoloe_module
from eovrt_media.models.yoloe_adapter import YOLOEUltralyticsAdapter


def _fake_model():
    fake = MagicMock()
    result = MagicMock()
    result.boxes = None
    fake.predict.return_value = [result]
    return fake


def test_yoloe_passes_half_on_cuda():
    adapter = YOLOEUltralyticsAdapter(device="cuda", half_precision=True)
    adapter.model = _fake_model()
    adapter.predict(Image.new("RGB", (8, 8)), ["person"])
    assert adapter.model.predict.call_args.kwargs["half"] is True


def test_yoloe_no_half_on_cpu():
    adapter = YOLOEUltralyticsAdapter(device="cpu", half_precision=True)
    adapter.model = _fake_model()
    adapter.predict(Image.new("RGB", (8, 8)), ["person"])
    assert adapter.model.predict.call_args.kwargs["half"] is False


def test_yoloe_forward_uses_shared_tensor_without_pil_conversion(monkeypatch):
    sentinel = torch.empty((1, 3, 8, 8))
    unit = NormalizedUnit(
        unit_id="unit-1",
        orig_width=8,
        orig_height=8,
        payload=np.zeros((8, 8, 3), dtype=np.float16),
        payload_format=PayloadFormat.FP16,
        target_size=(8, 8),
        transform=ResizeTransform(scale_x=1.0, scale_y=1.0, pad_x=0.0, pad_y=0.0),
    )
    adapter = YOLOEUltralyticsAdapter(device="cpu")
    adapter.model = _fake_model()
    monkeypatch.setattr(
        yoloe_module, "prepare_model_input", lambda *args, **kwargs: sentinel, raising=False
    )
    monkeypatch.setattr(
        yoloe_module.Image,
        "fromarray",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("PIL is not allowed")),
    )

    assert adapter.forward(unit, ["person"]) == []
    assert adapter.model.predict.call_args.kwargs["source"] is sentinel
