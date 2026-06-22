from eovrt_media.config.schemas import ModelSection
from eovrt_media.models import create_adapter


def test_model_runtime_defaults():
    m = ModelSection(adapter="yoloe")
    assert m.runtime.half_precision is True
    assert m.runtime.warmup is True


def test_factory_passes_runtime_to_yoloe():
    m = ModelSection(adapter="yoloe", device="cpu", runtime={"half_precision": False, "warmup": False})
    adapter = create_adapter(m)
    assert adapter.half_precision is False
    assert adapter.warmup is False


def test_factory_passes_runtime_to_gdino():
    m = ModelSection(adapter="grounding_dino", device="cpu", runtime={"half_precision": True, "warmup": True})
    adapter = create_adapter(m)
    assert adapter.half_precision is True
    assert adapter.warmup is True
