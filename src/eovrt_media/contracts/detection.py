"""Contratos para las detecciones."""

from __future__ import annotations

from dataclasses import dataclass
from pydantic import BaseModel, Field


@dataclass
class RawDetection:
    """Detección cruda producida por un adaptador antes de la normalización."""

    label: str
    score: float
    box_xyxy: list[float]  # [x1, y1, x2, y2] en píxeles
    source_prompt: str | None = None
    prompt_id: str | None = None
    raw: dict | None = None

    @property
    def bbox_xyxy(self) -> list[float]:
        """Alias para box_xyxy para cumplir con el esquema de la MEMORIA."""
        return self.box_xyxy


class Detection(BaseModel):
    """Detección normalizada producida por el plano de medios."""

    detection_id: str | None = None
    label: str
    prompt_id: str | None = None
    confidence: float
    bbox_xyxy: list[float] = Field(
        description="Bounding box en píxeles [x1, y1, x2, y2]"
    )
    bbox_norm_xyxy: list[float] = Field(
        description="Bounding box normalizado [0, 1] [x1, y1, x2, y2]"
    )
    area_px: float | None = None
    
    # Nombre del modelo que generó esta detección, cuando está disponible.
    model_name: str | None = None
