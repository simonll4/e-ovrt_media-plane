"""Colector de métricas de sistema y hardware para el plano de medios."""

from __future__ import annotations

import torch


def get_gpu_memory_allocated_mb() -> float:
    """Retorna la memoria GPU reservada/utilizada por PyTorch en megabytes.

    Si CUDA no está disponible o no se está utilizando GPU, retorna 0.0.
    """
    if torch.cuda.is_available():
        try:
            return torch.cuda.memory_allocated() / (1024.0 * 1024.0)
        except Exception:
            return 0.0
    return 0.0
