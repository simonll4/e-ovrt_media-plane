"""La cabeza de cajas de grounding-dino-base que transformers 5.x deja sin cargar (doc 134 §13.10)."""

from types import SimpleNamespace

import torch
from safetensors.torch import save_file
from torch import nn

from eovrt_media.models.grounding_dino_adapter import restore_decoder_bbox_head


class _Mlp(nn.Module):
    def __init__(self) -> None:
        super().__init__()
        self.layers = nn.ModuleList([nn.Linear(4, 4), nn.Linear(4, 2)])


class _FakeGdino(nn.Module):
    def __init__(self, share: bool = True) -> None:
        super().__init__()
        self.config = SimpleNamespace(decoder_bbox_embed_share=share)
        self.bbox_embed = nn.ModuleList([_Mlp()])
        for p in self.bbox_embed.parameters():
            nn.init.zeros_(p)


def _trained_head(prefix: str) -> dict:
    torch.manual_seed(0)
    return {
        f"{prefix}layers.0.weight": torch.randn(4, 4),
        f"{prefix}layers.0.bias": torch.randn(4),
        f"{prefix}layers.1.weight": torch.randn(2, 4),
        f"{prefix}layers.1.bias": torch.randn(2),
    }


def test_restaura_la_cabeza_guardada_como_decoder_bbox_embed(tmp_path):
    head = _trained_head("model.decoder.bbox_embed.0.")
    save_file({**head, "model.otro.weight": torch.ones(1)}, str(tmp_path / "model.safetensors"))
    model = _FakeGdino()

    assert restore_decoder_bbox_head(model, str(tmp_path)) is True
    assert torch.equal(model.bbox_embed[0].layers[1].weight, head["model.decoder.bbox_embed.0.layers.1.weight"])
    # Si ya está cargada (otra versión de transformers), no hace nada.
    assert restore_decoder_bbox_head(model, str(tmp_path)) is False


def test_tiny_guarda_la_cabeza_como_bbox_embed_y_no_se_toca(tmp_path):
    save_file(_trained_head("bbox_embed.0."), str(tmp_path / "model.safetensors"))
    model = _FakeGdino()

    assert restore_decoder_bbox_head(model, str(tmp_path)) is False
    assert not model.bbox_embed[0].layers[1].weight.any()


def test_sin_cabeza_compartida_no_restaura(tmp_path):
    save_file(_trained_head("model.decoder.bbox_embed.0."), str(tmp_path / "model.safetensors"))
    model = _FakeGdino(share=False)

    assert restore_decoder_bbox_head(model, str(tmp_path)) is False


def test_sin_checkpoint_local_ni_en_cache_no_hace_nada(tmp_path):
    assert restore_decoder_bbox_head(_FakeGdino(), str(tmp_path / "no-existe")) is False
