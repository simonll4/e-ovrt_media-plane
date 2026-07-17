"""Contrato del ledger de descartes por-frame (spec dropped-frames-ledger)."""

from __future__ import annotations

import time
from typing import Any, Literal

from pydantic import BaseModel

DropReason = Literal["rate_gate", "queue_full", "staleness_timeout", "channel_closed"]


class DroppedUnitRecord(BaseModel):
    schema_version: str = "media.dropped_unit.v1"
    run_id: str | None = None
    reason: DropReason
    unit_id: str
    frame_index: int | None = None
    timestamp_ms: float | None = None
    source_clock: str | None = None
    dropped_wallclock_ms: float


def build_dropped_record(unit: Any, reason: str, run_id: str | None) -> DroppedUnitRecord:
    """Arma el registro desde la unidad descartada (VisualUnit o NormalizedUnit).

    Duck-typing a proposito: ambos contratos comparten los campos de identidad.
    """
    return DroppedUnitRecord(
        run_id=run_id,
        reason=reason,  # Literal valida el reason
        unit_id=unit.unit_id,
        frame_index=unit.frame_index,
        timestamp_ms=unit.timestamp_ms,
        source_clock=getattr(unit, "source_clock", None),
        dropped_wallclock_ms=time.time() * 1000.0,
    )
