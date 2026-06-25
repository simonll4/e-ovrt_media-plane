"""Sinks para persistencia de resultados del pipeline."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from eovrt_media.contracts import DetectionEvent, MetricSample, RunSummary, ErrorEvent

logger = logging.getLogger(__name__)


class JSONLSink:
    """Escribe eventos de detección, métricas o errores a un archivo JSONL."""

    def __init__(self, output_path: Path) -> None:
        self.output_path = output_path
        self._file = None

    def open(self) -> None:
        """Abre el archivo para escritura."""
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        self._file = open(self.output_path, "w", encoding="utf-8")

    def write_event(self, event: DetectionEvent) -> None:
        """Escribe un DetectionEvent como una línea JSON."""
        if self._file is None:
            raise RuntimeError("Sink no abierto. Llamar open() primero.")
        line = event.model_dump_json(exclude_none=True)
        self._file.write(line + "\n")
        self._file.flush()

    def write_metric(self, metric: MetricSample) -> None:
        """Escribe un MetricSample como una línea JSON."""
        if self._file is None:
            raise RuntimeError("Sink no abierto. Llamar open() primero.")
        line = metric.model_dump_json(exclude_none=True)
        self._file.write(line + "\n")
        self._file.flush()

    def write_error(self, error: ErrorEvent) -> None:
        """Escribe un ErrorEvent como una línea JSON."""
        if self._file is None:
            raise RuntimeError("Sink no abierto. Llamar open() primero.")
        line = error.model_dump_json()
        self._file.write(line + "\n")
        self._file.flush()

    def close(self) -> None:
        """Cierra el archivo."""
        if self._file is not None:
            self._file.close()
            self._file = None


class SummarySink:
    """Escribe el resumen de corrida a un archivo JSON."""

    def __init__(self, output_path: Path) -> None:
        self.output_path = output_path

    def write(self, summary: RunSummary) -> None:
        """Escribe el RunSummary como JSON formateado."""
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.output_path, "w", encoding="utf-8") as f:
            json.dump(summary.model_dump(exclude_none=True), f, indent=2, ensure_ascii=False)
        logger.info(f"Resumen guardado en: {self.output_path}")
