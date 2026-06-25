import numpy as np
import pytest
import sys
from types import ModuleType
from unittest.mock import MagicMock

import torch

from eovrt_media.contracts.normalized_unit import (
    NormalizedUnit,
    PayloadFormat,
    ResizeTransform,
)
import eovrt_media.models.grounding_dino_adapter as gdino_module
from eovrt_media.models.grounding_dino_adapter import GroundingDinoHFAdapter


def test_gdino_predict_accepts_numpy():
    adapter = GroundingDinoHFAdapter(device="cpu")
    # processor que explota al ser invocado: confirma que pasamos el guard de tipo
    adapter.processor = MagicMock(side_effect=RuntimeError("reached processor"))
    adapter.model = MagicMock()
    with pytest.raises(RuntimeError, match="reached processor"):
        adapter.predict(np.zeros((8, 8, 3), dtype=np.uint8), ["person"])


def test_gdino_load_resolves_cuda_to_cpu_without_gpu(monkeypatch):
    monkeypatch.setattr(torch.cuda, "is_available", lambda: False)
    fake_transformers = ModuleType("transformers")
    fake_transformers.AutoProcessor = MagicMock()
    fake_model = MagicMock()
    fake_cls = MagicMock()
    fake_cls.from_pretrained.return_value.to.return_value = fake_model
    fake_transformers.AutoModelForZeroShotObjectDetection = fake_cls
    monkeypatch.setitem(sys.modules, "transformers", fake_transformers)

    adapter = GroundingDinoHFAdapter(device="cuda", warmup=False)
    adapter.load()

    assert adapter.device == "cpu"


def _float16_unit() -> NormalizedUnit:
    return NormalizedUnit(
        unit_id="unit-1",
        orig_width=8,
        orig_height=8,
        payload=np.zeros((8, 8, 3), dtype=np.float16),
        payload_format=PayloadFormat.FP16,
        target_size=(8, 8),
        transform=ResizeTransform(scale_x=1.0, scale_y=1.0, pad_x=0.0, pad_y=0.0),
    )


def test_gdino_forward_uses_shared_tensor_without_pil_conversion(monkeypatch):
    sentinel = torch.empty((1, 3, 8, 8))

    class TextInputs(dict):
        def to(self, device):
            return self

        @property
        def input_ids(self):
            return self["input_ids"]

    class TextOnlyProcessor:
        def __call__(self, *, text, return_tensors):
            assert text == "person."
            assert return_tensors == "pt"
            return TextInputs(input_ids=torch.tensor([[1, 2]]))

        def post_process_grounded_object_detection(self, *args, **kwargs):
            return [{"boxes": torch.empty((0, 4)), "scores": torch.empty(0), "text_labels": []}]

    adapter = GroundingDinoHFAdapter(device="cpu")
    adapter.processor = TextOnlyProcessor()
    adapter.model = MagicMock()
    monkeypatch.setattr(
        gdino_module, "prepare_model_input", lambda *args, **kwargs: sentinel, raising=False
    )
    monkeypatch.setattr(
        gdino_module.Image,
        "fromarray",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("PIL is not allowed")),
    )

    assert adapter.forward(_float16_unit(), ["person"]) == []
    assert adapter.model.call_args.kwargs["pixel_values"] is sentinel
