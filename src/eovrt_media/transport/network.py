"""Backend de transporte ZeroMQ REQ/REP entre Nodo A (productor) y Nodo B (consumidor).

La política de rate control NO cambia: el lado productor reutiliza el buffer
bounded_freshness (head-drop). ZeroMQ es solo el canal entre los dos lados.
"""
from __future__ import annotations

import threading
import time

import zmq

from eovrt_media.contracts.normalized_unit import END, NormalizedUnit
from eovrt_media.transport.base import TransportAdapter
from eovrt_media.transport.memory import MemoryTransportAdapter
from eovrt_media.transport.serialization import (
    END_MSG, REQUEST, deserialize_unit, is_control, serialize_unit,
)


class NetworkTransportAdapter(TransportAdapter):
    """Adaptador de red con dos roles que comparten interfaz.

    role="producer": bind REP; sirve frames del buffer bounded_freshness.
    role="consumer": connect REQ; pide frames hasta recibir END.
    """

    def __init__(
        self,
        role: str,
        endpoint: str,
        policy: str = "bounded_freshness",
        buffer_size: int = 2,
        max_staleness_ms: float | None = None,
        heartbeat_interval_ms: int = 1000,
        heartbeat_timeout_ms: int = 5000,
    ) -> None:
        if role not in {"producer", "consumer"}:
            raise ValueError(f"role debe ser 'producer' o 'consumer', no {role!r}.")
        self.role = role
        self.endpoint = endpoint
        self._ctx = zmq.Context.instance()
        self.heartbeat_interval_ms = heartbeat_interval_ms
        self.heartbeat_timeout_ms = heartbeat_timeout_ms
        self._last_peer_activity = None

        if role == "producer":
            self._buffer = MemoryTransportAdapter(
                policy=policy, buffer_size=buffer_size, max_staleness_ms=max_staleness_ms
            )
            self.units_dropped = 0
            self._sock = self._ctx.socket(zmq.REP)
            self._sock.bind(endpoint)
            self._server = threading.Thread(target=self._serve, name="net-rep-server", daemon=True)
            self._server.start()
        else:
            self._sock = self._ctx.socket(zmq.REQ)
            self._sock.connect(endpoint)

    # --- productor ---

    def offer(self, unit: NormalizedUnit) -> None:
        self._buffer.offer(unit)

    def close(self) -> None:
        """Señala fin de stream al buffer; el server enviará END a los REQUEST."""
        self._buffer.close()

    def _serve(self) -> None:
        """Hilo REP: por cada REQUEST entrega el frame más antiguo o END."""
        while True:
            msg = self._sock.recv()
            self._last_peer_activity = time.monotonic()
            if not is_control(msg):
                continue  # solo REQUEST/HEARTBEAT esperados del consumidor
            item = self._buffer.request()  # bloquea hasta frame o END
            if item is END:
                self._sock.send(END_MSG)
                return
            self._sock.send(serialize_unit(item))

    def is_peer_alive(self) -> bool:
        """True si el consumidor mostró actividad dentro del timeout (lado productor)."""
        if self.role != "producer" or self._last_peer_activity is None:
            return False
        elapsed_ms = (time.monotonic() - self._last_peer_activity) * 1000.0
        return elapsed_ms <= self.heartbeat_timeout_ms

    # --- consumidor ---

    def request(self, **kwargs) -> NormalizedUnit | type[END]:
        self._sock.send(REQUEST)
        data = self._sock.recv()
        if data == END_MSG:
            return END
        return deserialize_unit(data)

    def shutdown(self) -> None:
        """Cierra socket y, en producer, espera el hilo servidor."""
        if self.role == "producer" and self._server.is_alive():
            self._server.join(timeout=5.0)
        self._sock.close(linger=0)

    @property
    def buffer_units_dropped(self) -> int:
        return getattr(self._buffer, "units_dropped", 0) if self.role == "producer" else 0
