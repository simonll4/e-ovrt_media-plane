"""Sink JSONL thread-safe para el ledger de descartes.

Serializa con lock: recibe escrituras del hilo productor (rate_gate/offer) y del
consumidor (staleness en request). Apertura perezosa: cero descartes = sin archivo.
"""

from __future__ import annotations

import json
from pathlib import Path
from threading import Lock

from eovrt_media.contracts.dropped_unit import DroppedUnitRecord


class DroppedUnitsSink:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = Lock()
        self._fh = None
        self._closed = False

    def write(self, record: DroppedUnitRecord) -> None:
        line = json.dumps(record.model_dump(mode="json"), ensure_ascii=True)
        with self._lock:
            if self._closed:
                # Best-effort: registros tardíos durante el teardown (hilo productor
                # todavía vivo tras el join con timeout) se descartan, nunca reabren
                # el archivo — reabrir en modo "w" truncaría el ledger ya cerrado.
                return
            if self._fh is None:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                self._fh = self.path.open("w", encoding="utf-8")
            self._fh.write(line + "\n")

    def close(self) -> None:
        with self._lock:
            self._closed = True
            if self._fh is not None:
                self._fh.close()
                self._fh = None
