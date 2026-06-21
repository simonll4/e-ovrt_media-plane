"""RateGate — filtro determinista de frames por stride."""

from __future__ import annotations


class RateGate:
    """Filtro de frames por stride. Solo para política deterministic."""

    def __init__(self, stride: int = 1) -> None:
        if stride < 1:
            raise ValueError(f"stride debe ser >= 1, recibido: {stride}")
        self.stride = stride

    def should_pass(self, frame_index: int) -> bool:
        return frame_index % self.stride == 0
