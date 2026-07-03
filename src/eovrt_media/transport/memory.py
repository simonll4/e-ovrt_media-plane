"""Backend de transporte en memoria — cola acotada con dos políticas."""

from __future__ import annotations

import queue
import time
from collections import deque
from threading import Lock

from eovrt_media.contracts.normalized_unit import NormalizedUnit, END, STALL
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
            self._det_closed = False
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
            while not self._det_closed:
                try:
                    self._q.put(unit, timeout=0.1)  # backpressure con chequeo de cierre
                    return
                except queue.Full:
                    continue
            self.units_dropped += 1  # canal cerrado: descartar
        else:
            with self._not_empty:
                if len(self._buf) == self._buf.maxlen:
                    self._buf.popleft()
                    self.units_dropped += 1
                self._buf.append(unit)
                self._not_empty.notify()

    def close(self) -> None:
        if self.policy == "deterministic":
            if self._det_closed:
                return
            self._det_closed = True
            try:
                self._q.put_nowait(END)
            except queue.Full:
                pass  # request() detecta _det_closed al vaciar la cola
        else:
            with self._not_empty:
                self._closed = True
                self._not_empty.notify_all()

    # --- consumidor ---

    def request(
        self, current_time_ms=None, timeout: float | None = None
    ) -> NormalizedUnit | type[END] | type[STALL]:
        """Obtiene la siguiente unidad, o ``END``/``STALL``.

        ``timeout`` es opt-in: si se omite (``None``), el comportamiento es
        IDÉNTICO al histórico (bloquea hasta que haya unidad o el canal
        cierre). Si se pasa, la llamada retorna ``STALL`` tras ese lapso sin
        unidad ni cierre — usado por el consumidor para re-chequear un stop
        cooperativo sin quedar bloqueado para siempre si el productor nunca
        cierra el canal (p.ej. fuente colgada que ignora ``stop()``).
        """
        deadline = time.monotonic() + timeout if timeout is not None else None
        if self.policy == "deterministic":
            poll_interval = 0.1
            while True:
                wait = poll_interval
                if deadline is not None:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        return STALL
                    wait = min(poll_interval, remaining)
                try:
                    item = self._q.get(timeout=wait)
                except queue.Empty:
                    if self._det_closed:
                        return END
                    if deadline is not None and time.monotonic() >= deadline:
                        return STALL
                    continue
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
                    if deadline is not None:
                        remaining = deadline - time.monotonic()
                        if remaining <= 0:
                            return STALL
                        self._not_empty.wait(timeout=remaining)
                    else:
                        self._not_empty.wait()
