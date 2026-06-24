"""Helpers de runtime para adaptadores de modelo (device, fp16, warmup)."""
from __future__ import annotations

import logging

import numpy as np

logger = logging.getLogger(__name__)


def resolve_device(requested: str, cuda_available: bool | None = None) -> str:
    """Normaliza el device: degrada a cpu si se pide cuda y no hay GPU."""
    if cuda_available is None:
        import torch

        cuda_available = torch.cuda.is_available()
    if requested.startswith("cuda") and not cuda_available:
        logger.warning("device=%s solicitado sin CUDA disponible; usando cpu", requested)
        return "cpu"
    return requested


def should_use_half(device: str, half_precision: bool) -> bool:
    """fp16 solo cuando el flag está activo y el device es CUDA."""
    return bool(half_precision) and device.startswith("cuda")


def make_warmup_image(target_size: tuple[int, int]) -> np.ndarray:
    """Imagen negra uint8 (H, W, 3) para el warmup del modelo."""
    h, w = target_size
    return np.zeros((h, w, 3), dtype=np.uint8)
