"""Tests for YOLOE fp16, warmup, and device resolution (Task 5)."""
from unittest.mock import MagicMock

from PIL import Image

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
