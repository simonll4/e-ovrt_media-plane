"""Event sink in-process: pipeline → WebSocket, sin acoplar el pipeline al servidor."""

from __future__ import annotations

import time
from collections import deque
from threading import Lock
from typing import Any, Protocol

_COALESCE_TYPES = {"metric"}


class RunEventSink(Protocol):
    def emit(self, event: dict[str, Any]) -> None: ...


class Subscriber:
    """Cola por-suscriptor: coalesce métricas (último gana), acota lo discreto."""

    def __init__(self, max_discrete: int = 200) -> None:
        self._lock = Lock()
        self._latest: dict[str, dict[str, Any]] = {}
        self._discrete: deque[dict[str, Any]] = deque(maxlen=max_discrete)

    def push(self, event: dict[str, Any]) -> None:
        with self._lock:
            if event.get("type") in _COALESCE_TYPES:
                self._latest[event["type"]] = event
            else:
                self._discrete.append(event)

    def drain(self) -> list[dict[str, Any]]:
        with self._lock:
            out = list(self._discrete)
            self._discrete.clear()
            out.extend(self._latest.values())
            self._latest.clear()
            return out


class EventBroadcaster:
    """RunEventSink que reparte a N suscriptores; nunca bloquea al pipeline."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._subscribers: set[Subscriber] = set()
        self.last_event_monotonic: float = time.monotonic()

    def subscribe(self) -> Subscriber:
        sub = Subscriber()
        with self._lock:
            self._subscribers.add(sub)
        return sub

    def unsubscribe(self, sub: Subscriber) -> None:
        with self._lock:
            self._subscribers.discard(sub)

    def emit(self, event: dict[str, Any]) -> None:
        self.last_event_monotonic = time.monotonic()
        with self._lock:
            subscribers = list(self._subscribers)
        for sub in subscribers:
            sub.push(event)


class EventEmittingArtifactWriter:
    """Decora RunArtifactWriter: persiste como siempre y además emite eventos."""

    def __init__(self, inner: Any, sink: RunEventSink) -> None:
        self._inner = inner
        self._sink = sink

    def write_detection(self, event: Any) -> None:
        self._inner.write_detection(event)
        self._sink.emit(
            {"type": "detection", "unit_id": event.unit_id, "count": len(event.detections)}
        )

    def write_metric(self, sample: Any) -> None:
        self._inner.write_metric(sample)
        self._sink.emit(
            {
                "type": "metric",
                "unit_id": sample.unit_id,
                "fps": sample.fps_effective,
                "latency_total_ms": sample.latency_total_ms,
                "detections_count": sample.detections_count,
                "gpu_memory_mb": sample.gpu_memory_allocated_mb,
            }
        )

    def write_error(self, event: Any) -> None:
        self._inner.write_error(event)
        self._sink.emit(
            {
                "type": "error",
                "unit_id": getattr(event, "unit_id", None),
                "stage": getattr(event, "stage", None),
                "message": getattr(event, "message", None),
            }
        )

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)
