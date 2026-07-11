"""Contrato para la unidad visual."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any
from pydantic import BaseModel, ConfigDict, Field, model_validator


class VisualUnit(BaseModel):
    """Representa una imagen o frame procesable."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    run_id: str | None = None
    unit_id: str
    source_id: str | None = None
    source_type: str  # "image" | "video_frame"
    # Instante en que el PROCESO leyo la unidad (spec 42 SS5.1). El default_factory
    # se evalua al construir el VisualUnit, que es exactamente el momento de lectura:
    # ninguna fuente puede olvidarse de estamparlo.
    capture_monotonic_ns: int = Field(default_factory=time.monotonic_ns)
    capture_wallclock_ms: float = Field(default_factory=lambda: time.time() * 1000.0)
    # Que reloj emite `timestamp_ms` esta fuente: wallclock | media | none.
    # Decide la aplicabilidad de t_capture->alert (spec 40 SS5.2.3).
    source_clock: str = "none"
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
