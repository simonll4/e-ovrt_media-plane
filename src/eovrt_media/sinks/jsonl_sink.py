"""Sinks para persistencia de resultados del pipeline."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

from eovrt_media.contracts import DetectionEvent, MetricSample, RunSummary, ErrorEvent

logger = logging.getLogger(__name__)


def atomic_write_json(
    path: Path, data: Any, *, indent: int = 2, ensure_ascii: bool = False
) -> None:
    """Escribe ``data`` como JSON en ``path`` de forma atómica.

    Escribe primero a un archivo temporal en el mismo directorio y lo
    sustituye con ``os.replace`` (atómico a nivel de filesystem), evitando
    dejar un JSON truncado si el proceso muere a mitad de escritura
    (kill/OOM).
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(path.name + ".tmp")
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=indent, ensure_ascii=ensure_ascii)
    except Exception:
        # Falla a mitad de escritura del .tmp (disco lleno, error de
        # serialización, etc.): no dejar basura .tmp en disco. El destino
        # real (path) todavía no fue tocado — os.replace() no se llegó a
        # ejecutar — así que queda intacto.
        tmp_path.unlink(missing_ok=True)
        raise
    os.replace(tmp_path, path)


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
        data = metric.model_dump(mode="json", exclude_none=True)
        # g2a_ms=None es informativo (no medible, p.ej. topologia two_node: spec
        # 40 SS4), no un campo ausente: a diferencia del resto de los campos
        # opcionales, NUNCA se omite. Si se omitiera, un consumidor que joinea
        # por unit_id no podria distinguir "no interpretable en esta topologia"
        # de "artefacto de un schema anterior a esta metrica".
        data["g2a_ms"] = metric.g2a_ms
        line = json.dumps(data, ensure_ascii=False)
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
        """Escribe el RunSummary como JSON formateado, de forma atómica."""
        atomic_write_json(self.output_path, summary.model_dump(exclude_none=True))
        logger.info(f"Resumen guardado en: {self.output_path}")
