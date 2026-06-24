"""Contrato NormalizedUnit — payload normalizado espacialmente que viaja por el canal."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

import numpy as np
from pydantic import BaseModel, ConfigDict


class PayloadFormat(str, Enum):
    UINT8_RGB = "uint8_rgb"  # impl
    FP32 = "fp32"            # impl
    FP16 = "fp16"            # declarado, no implementado


@dataclass
class ResizeTransform:
    """Parámetros del resize aplicado al payload — necesarios para reproyectar cajas."""

    scale_x: float
    scale_y: float
    pad_x: float  # píxeles de padding horizontal (izquierda)
    pad_y: float  # píxeles de padding vertical (arriba)

    def project_to_original(self, box_xyxy: list[float]) -> list[float]:
        """Proyecta una caja de espacio-modelo a píxeles originales."""
        x1, y1, x2, y2 = box_xyxy
        return [
            (x1 - self.pad_x) / self.scale_x,
            (y1 - self.pad_y) / self.scale_y,
            (x2 - self.pad_x) / self.scale_x,
            (y2 - self.pad_y) / self.scale_y,
        ]


class NormalizedUnit(BaseModel):
    """Unidad normalizada espacialmente que viaja por el canal productor→consumidor."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    run_id: str | None = None
    unit_id: str
    source_id: str | None = None
    source_path: str | None = None
    frame_index: int | None = None
    timestamp_ms: float | None = None

    orig_width: int
    orig_height: int

    payload: np.ndarray
    payload_format: PayloadFormat = PayloadFormat.UINT8_RGB
    target_size: tuple[int, int]  # (H, W) del payload
    transform: ResizeTransform


class END:
    """Sentinel de fin de canal — el productor lo emite al agotar la fuente."""
