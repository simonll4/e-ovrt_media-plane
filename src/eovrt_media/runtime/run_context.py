"""Contexto de ejecución de una corrida del pipeline."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from eovrt_media.config import RunConfig


class RunContext:
    """Administra el estado y las métricas acumuladas de una corrida."""

    def __init__(self, config: RunConfig) -> None:
        self.config = config
        self.started_at = datetime.now(timezone.utc)
        self.finished_at: datetime | None = None

        # Generar run_id
        if config.run.id:
            self.run_id = config.run.id
        else:
            ts = self.started_at.strftime("%Y%m%d_%H%M%S")
            suffix = config.run.name or config.model.adapter or "run"
            self.run_id = f"run_{ts}_{suffix}"

        # Directorio de salida
        self.run_dir = Path(config.outputs.run_dir) / self.run_id

        # Métricas de ejecución
        self.units_processed = 0
        self.units_failed = 0
        self.total_detections = 0
        self.errors_count = 0

    def finish(self) -> None:
        """Finaliza la corrida registrando el timestamp de fin."""
        self.finished_at = datetime.now(timezone.utc)

    @property
    def duration_seconds(self) -> float:
        """Duración de la corrida en segundos."""
        end = self.finished_at or datetime.now(timezone.utc)
        return (end - self.started_at).total_seconds()
