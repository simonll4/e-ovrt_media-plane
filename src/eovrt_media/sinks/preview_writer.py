"""Escritura de previews anotadas fuera del hilo consumidor.

La preview es observación, no parte del flujo operativo: dibujarla y escribirla en el
consumidor demoraba la publicación de la detección al bus y el siguiente cuadro (~19 ms
por cuadro en el bind mount de Docker Desktop sobre Windows, medido 2026-10-24). Un
hilo propio con cola acotada la saca del camino caliente: si la cola se llena, la
preview se descarta y la inferencia nunca espera. close() drena lo pendiente, así que
al terminar la corrida las previews encoladas ya están en disco.
"""

from __future__ import annotations

import logging
import queue
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

from eovrt_media.visualize import draw_detections_rgb

logger = logging.getLogger(__name__)

_STOP = object()


class AsyncPreviewWriter:
    def __init__(
        self, draw: Callable[..., None] = draw_detections_rgb, max_pending: int = 4
    ) -> None:
        self._draw = draw
        self._queue: queue.Queue = queue.Queue(maxsize=max_pending)
        self._errors: queue.SimpleQueue = queue.SimpleQueue()
        self.dropped = 0
        self._closed = False
        self._thread = threading.Thread(target=self._run, name="preview-writer", daemon=True)
        self._thread.start()

    def submit(self, unit_id: str, payload: Any, detections: list, path: Path, **kwargs: Any) -> bool:
        """Encola una preview sin bloquear; False si se descartó por cola llena."""
        if self._closed:
            return False
        try:
            self._queue.put_nowait((unit_id, payload, list(detections), path, kwargs))
        except queue.Full:
            self.dropped += 1
            return False
        return True

    def drain_errors(self) -> list[tuple[str, str]]:
        """Errores (unit_id, mensaje) acumulados por el hilo, para reportarlos desde el
        consumidor (que es quien escribe errors.jsonl)."""
        errors = []
        while True:
            try:
                errors.append(self._errors.get_nowait())
            except queue.Empty:
                return errors

    def close(self, timeout: float = 30.0) -> list[tuple[str, str]]:
        """Drena lo encolado, detiene el hilo y devuelve los errores pendientes."""
        if not self._closed:
            self._closed = True
            self._queue.put(_STOP)
            self._thread.join(timeout)
            if self._thread.is_alive():
                logger.warning("preview-writer no terminó en %.0fs; previews pendientes perdidas", timeout)
            if self.dropped:
                logger.warning("previews descartadas por cola llena: %d", self.dropped)
        return self.drain_errors()

    def _run(self) -> None:
        while True:
            job = self._queue.get()
            if job is _STOP:
                return
            unit_id, payload, detections, path, kwargs = job
            try:
                self._draw(payload, detections, path, **kwargs)
            except Exception as exc:  # noqa: BLE001 — una preview rota no corta la corrida
                self._errors.put((unit_id, str(exc)))
