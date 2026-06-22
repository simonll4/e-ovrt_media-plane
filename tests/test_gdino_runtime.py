from unittest.mock import MagicMock

import torch

import eovrt_media.models.grounding_dino_adapter as gd
from eovrt_media.models.grounding_dino_adapter import GroundingDinoHFAdapter


def test_gdino_load_resolves_cuda_to_cpu_without_gpu(monkeypatch):
    monkeypatch.setattr(torch.cuda, "is_available", lambda: False)
    monkeypatch.setattr(gd, "AutoProcessor", MagicMock())
    fake_model = MagicMock()
    fake_cls = MagicMock()
    fake_cls.from_pretrained.return_value.to.return_value = fake_model
    monkeypatch.setattr(gd, "AutoModelForZeroShotObjectDetection", fake_cls)

    adapter = GroundingDinoHFAdapter(device="cuda", warmup=False)
    adapter.load()

    assert adapter.device == "cpu"
