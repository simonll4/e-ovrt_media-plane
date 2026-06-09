"""Contratos para los eventos de error."""

from __future__ import annotations

from pydantic import BaseModel


class ErrorEvent(BaseModel):
    """Evento de error registrado en la ejecución del pipeline."""

    schema_version: str = "media.error.v1"
    event_type: str = "error_event"
    run_id: str
    unit_id: str | None = None
    stage: str
    severity: str = "error"  # "warning" | "error" | "fatal"
    message: str
    recoverable: bool = True
