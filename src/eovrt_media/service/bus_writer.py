"""Publicacion al bus media->control: decorador del RunArtifactWriter (spec 42 SS2).

Hermano de `EventEmittingArtifactWriter` (service/events.py): aquel emite resumenes
para el WebSocket de la consola; este publica el `DetectionEvent` COMPLETO, ya
persistido, para el plano de control. Son piezas distintas.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from eovrt_media.transport.bus import (
    DETECTION_TOPIC_PREFIX,
    LIFECYCLE_SCHEMA_VERSION,
    LIFECYCLE_TOPIC_PREFIX,
    BusPublisher,
)

logger = logging.getLogger(__name__)


class BusPublishingArtifactWriter:
    """Persiste como siempre y ademas publica al bus. El JSONL es la verdad."""

    def __init__(self, inner: Any, publisher: BusPublisher, run_id: str) -> None:
        self._inner = inner
        self._publisher = publisher
        self._run_id = run_id
        self._detection_topic = f"{DETECTION_TOPIC_PREFIX}{run_id}"
        self._lifecycle_topic = f"{LIFECYCLE_TOPIC_PREFIX}{run_id}"

    def write_detection(self, event: Any) -> None:
        # Persistir PRIMERO: si el bus se cae, el artefacto ya esta en disco.
        self._inner.write_detection(event)
        # Byte-compatible con JsonlSink.write_event (spec 40 SS3.1): el evento del
        # bus y el releido del archivo son el mismo objeto.
        payload = event.model_dump_json(exclude_none=True).encode("utf-8")
        self._publisher.publish(self._detection_topic, event.source.source_id, payload)

    def publish_run_finished(self, status: str) -> None:
        """Sentinela END de la corrida 1:1 (ADR-007)."""
        payload = json.dumps(
            {
                "schema_version": LIFECYCLE_SCHEMA_VERSION,
                "event": "run_finished",
                "media_run_id": self._run_id,
                "status": status,
            }
        ).encode("utf-8")
        self._publisher.publish(self._lifecycle_topic, self._run_id, payload)

    def close(self) -> None:
        self._inner.close()

    def __getattr__(self, name: str) -> Any:
        # Si _inner no existe (p.ej. __init__ fallo antes de asignarlo), delegar
        # a self._inner recursaria: __getattr__ se llamaria a si mismo buscando
        # _inner. Cortar con AttributeError directo evita el RecursionError.
        if name == "_inner":
            raise AttributeError(name)
        return getattr(self._inner, name)
