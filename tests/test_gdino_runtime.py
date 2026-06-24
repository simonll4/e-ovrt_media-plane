import numpy as np
import pytest
import sys
from types import ModuleType
from unittest.mock import MagicMock

import torch

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
