"""Contrato para la unidad visual."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from pydantic import BaseModel, ConfigDict, model_validator


class VisualUnit(BaseModel):
    """Representa una imagen o frame procesable."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    run_id: str | None = None
    unit_id: str
    source_id: str | None = None
    source_type: str  # "image" | "video_frame"
    frame_index: int | None = None
    timestamp_ms: float | None = None
    width: int
    height: int
    path: str | None = None
    source_path: str | None = None
    # Frame capturado por fuentes vivas (RTSP). BGR numpy array.
    # Cuando está presente, image_loader lo usa directamente sin reabrir la fuente.
    pixel_data: Any = None

    @model_validator(mode="before")
    @classmethod
    def sync_paths_and_ids(cls, data: Any) -> Any:
        if isinstance(data, dict):
            p = data.get("path") or data.get("source_path")
            if p:
                data["path"] = p
                data["source_path"] = p
                if not data.get("source_id"):
                    data["source_id"] = Path(p).name
        return data
