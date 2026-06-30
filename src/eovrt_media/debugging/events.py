"""Structured debug events for media-plane diagnostic runs."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field


DebugNode = Literal["A", "B", "session", "single_host", "transport"]


class DebugEvent(BaseModel):
    """One structured diagnostic event."""

    schema_version: str = "media.debug.v1"
    ts: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    run_id: str | None = None
    node: DebugNode
    stage: str
    event: str
    unit_id: str | None = None
    elapsed_ms: float | None = None
    payload_bytes: int | None = None
    codec: str | None = None
    device: str | None = None
    message: str | None = None
    extra: dict[str, Any] = Field(default_factory=dict)


class DebugEventWriter:
    """Write JSONL debug events, or act as a no-op when disabled."""

    def __init__(self, path: Path, *, enabled: bool) -> None:
        self.path = path
        self.enabled = enabled
        self._file = None
        if enabled:
            path.parent.mkdir(parents=True, exist_ok=True)
            self._file = path.open("w", encoding="utf-8")

    def write(self, **kwargs: Any) -> None:
        if not self.enabled or self._file is None:
            return
        event = DebugEvent(**kwargs)
        self._file.write(event.model_dump_json(exclude_none=True) + "\n")
        self._file.flush()

    def close(self) -> None:
        if self._file is not None:
            self._file.close()
            self._file = None
