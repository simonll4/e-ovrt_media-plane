"""Tests for ModelInputSpec dataclass and input_spec property on all adapters."""

from eovrt_media.models.base import ModelInputSpec
from eovrt_media.models.mock_detector import MockDetectorAdapter
from eovrt_media.models import create_adapter
from eovrt_media.config.schemas import ModelSection


class TestModelInputSpec:
    def test_dataclass_fields(self):
        spec = ModelInputSpec(
            target_size=(800, 800),
            resize_mode="letterbox",
            mean=(0.485, 0.456, 0.406),
            std=(0.229, 0.224, 0.225),
        )
        assert spec.target_size == (800, 800)
        assert spec.dtype == "float32"       # default
        assert spec.channel_order == "rgb"   # default

    def test_dataclass_defaults(self):
        spec = ModelInputSpec(target_size=(640, 640))
        assert spec.resize_mode == "letterbox"
        assert spec.channel_order == "rgb"
        assert spec.mean == (0.485, 0.456, 0.406)
        assert spec.std == (0.229, 0.224, 0.225)
        assert spec.dtype == "float32"

    def test_mock_adapter_has_input_spec(self):
        adapter = MockDetectorAdapter()
        spec = adapter.input_spec
        assert isinstance(spec, ModelInputSpec)
        assert len(spec.target_size) == 2
        assert spec.target_size[0] > 0 and spec.target_size[1] > 0

    def test_gdino_adapter_has_input_spec(self):
        section = ModelSection(adapter="grounding_dino_hf", device="cpu")
        adapter = create_adapter(section)
        spec = adapter.input_spec
        assert spec.target_size == (800, 800)
        assert spec.resize_mode == "letterbox"

    def test_yoloe_adapter_has_input_spec(self):
        section = ModelSection(adapter="yoloe", device="cpu")
        adapter = create_adapter(section)
        spec = adapter.input_spec
        assert spec.target_size == (640, 640)
        assert spec.resize_mode == "letterbox"
