"""Backend de transporte en memoria — cola acotada con dos políticas."""

from __future__ import annotations

import queue
import time
from collections import deque
from threading import Lock

from eovrt_media.contracts.normalized_unit import NormalizedUnit, END
from eovrt_media.transport.base import TransportAdapter


class MemoryTransportAdapter(TransportAdapter):
    """Cola en memoria con políticas deterministic y bounded_freshness."""

    def __init__(
        self,
        policy: str = "deterministic",
        max_queue_size: int = 8,
        buffer_size: int = 2,
        max_staleness_ms: float | None = None,
    ) -> None:
        self.policy = policy
        self.max_staleness_ms = max_staleness_ms
        self.units_dropped: int = 0

        if policy == "deterministic":
            self._q: queue.Queue = queue.Queue(maxsize=max_queue_size)
        elif policy == "bounded_freshness":
            self._buf: deque = deque(maxlen=buffer_size)
            self._lock = Lock()
            self._not_empty = __import__("threading").Condition(self._lock)
            self._closed = False
        else:
            raise ValueError(f"Política desconocida: {policy!r}")

    # --- productor ---

    def offer(self, unit: NormalizedUnit) -> None:
        if self.policy == "deterministic":
            self._q.put(unit)  # bloquea si llena (backpressure)
        else:
            with self._not_empty:
                if len(self._buf) == self._buf.maxlen:
                    self._buf.popleft()
                    self.units_dropped += 1
                self._buf.append(unit)
                self._not_empty.notify()

    def close(self) -> None:
        if self.policy == "deterministic":
            self._q.put(END)
        else:
            with self._not_empty:
                self._closed = True
                self._not_empty.notify_all()

    # --- consumidor ---

    def request(self, current_time_ms=None) -> NormalizedUnit | type[END]:
        if self.policy == "deterministic":
            item = self._q.get()
            return END if item is END else item
        else:
            with self._not_empty:
                while True:
                    if self._buf:
                        unit = self._buf.popleft()
                        if self.max_staleness_ms is not None and unit.timestamp_ms is not None:
                            now = (current_time_ms() if current_time_ms else time.time() * 1000)
                            if now - unit.timestamp_ms > self.max_staleness_ms:
                                self.units_dropped += 1
                                continue
                        return unit
                    if self._closed:
                        return END
                    self._not_empty.wait()
