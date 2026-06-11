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


def reset_gpu_peak_memory() -> None:
    """Reinicia el contador de memoria GPU pico de PyTorch.

    Llamar al inicio de la corrida para que el pico refleje solo esta ejecución.
    """
    if torch.cuda.is_available():
        try:
            torch.cuda.reset_peak_memory_stats()
        except Exception:
            pass


def get_gpu_memory_peak_mb() -> float:
    """Retorna la memoria GPU máxima asignada por PyTorch en megabytes.

    Es la "VRAM máxima observada" de la corrida (desde el último reset).
    Si CUDA no está disponible, retorna 0.0.
    """
    if torch.cuda.is_available():
        try:
            return torch.cuda.max_memory_allocated() / (1024.0 * 1024.0)
        except Exception:
            return 0.0
    return 0.0
