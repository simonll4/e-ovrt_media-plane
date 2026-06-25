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

# Sentinel propio del canal heartbeat PUSH/PULL — independiente del esquema CTRL de serialization.py
HEARTBEAT = b"HEARTBEAT"


class NetworkTransportAdapter(TransportAdapter):
    """Adaptador de red con dos roles que comparten interfaz.

    role="producer": bind REP de datos y PULL de heartbeat.
    role="consumer": connect REQ de datos y emite heartbeat por PUSH.
    """

    def __init__(
        self,
        role: str,
        endpoint: str,
        heartbeat_endpoint: str,
        policy: str = "bounded_freshness",
        buffer_size: int = 2,
        max_staleness_ms: float | None = None,
        heartbeat_interval_ms: int = 1000,
        heartbeat_timeout_ms: int = 5000,
        codec: str = "jpeg",
        quality: int = 90,
    ) -> None:
        if role not in {"producer", "consumer"}:
            raise ValueError(f"role debe ser 'producer' o 'consumer', no {role!r}.")
        self.role = role
        self.endpoint = endpoint
        self.heartbeat_endpoint = heartbeat_endpoint
        self._ctx = zmq.Context.instance()
        self.heartbeat_interval_ms = heartbeat_interval_ms
        self.heartbeat_timeout_ms = heartbeat_timeout_ms
        self._last_heartbeat: float | None = None
        self.codec = codec
        self.quality = quality

        if role == "producer":
            self._buffer = MemoryTransportAdapter(
                policy=policy, buffer_size=buffer_size, max_staleness_ms=max_staleness_ms
            )
            self.units_dropped = 0
            self._closed = False
            self._shutdown_event = threading.Event()
            self._server_ready = threading.Event()
            self._heartbeat_server_ready = threading.Event()
            self._server_error: Exception | None = None
            self._server = threading.Thread(target=self._serve, name="net-rep-server", daemon=True)
            self._heartbeat_server = threading.Thread(
                target=self._serve_heartbeats,
                name="net-heartbeat-server",
                daemon=True,
            )
            self._server.start()
            self._heartbeat_server.start()
            self._server_ready.wait()
            self._heartbeat_server_ready.wait()
            if self._server_error is not None:
                self._shutdown_event.set()
                self._server.join(timeout=5.0)
                self._heartbeat_server.join(timeout=5.0)
                raise self._server_error
        else:
            self._sock = self._ctx.socket(zmq.REQ)
            self._sock.connect(endpoint)
            self._heartbeat_shutdown_event = threading.Event()
            self._heartbeat_thread = threading.Thread(
                target=self._send_heartbeats,
                name="net-heartbeat-client",
                daemon=True,
            )
            self._heartbeat_thread.start()

    # --- productor ---

    def offer(self, unit: NormalizedUnit) -> None:
        self._buffer.offer(unit)

    def close(self) -> None:
        """Señala fin de stream al buffer; el server enviará END a los REQUEST."""
        if self.role == "producer" and not self._closed:
            self._buffer.close()
            self._closed = True

    def _serve(self) -> None:
        """Hilo REP: por cada REQUEST entrega el frame más antiguo o END."""
        sock = self._ctx.socket(zmq.REP)
        try:
            sock.bind(self.endpoint)
        except Exception as exc:
            self._server_error = exc
            self._server_ready.set()
            sock.close(linger=0)
            return

        self._server_ready.set()
        poller = zmq.Poller()
        poller.register(sock, zmq.POLLIN)
        try:
            while not self._shutdown_event.is_set():
                events = dict(poller.poll(timeout=100))
                if sock in events:
                    msg = sock.recv()
                    if not is_control(msg):
                        sock.send(END_MSG)
                        continue
                    item = self._buffer.request()  # bloquea hasta frame o END
                    if item is END:
                        sock.send(END_MSG)
                        return
                    sock.send(serialize_unit(item, codec=self.codec, quality=self.quality))
        finally:
            poller.unregister(sock)
            sock.close(linger=0)

    def _serve_heartbeats(self) -> None:
        """Hilo PULL independiente para que liveness no espere al canal de datos."""
        sock = self._ctx.socket(zmq.PULL)
        try:
            sock.bind(self.heartbeat_endpoint)
        except Exception as exc:
            self._server_error = exc
            self._heartbeat_server_ready.set()
            sock.close(linger=0)
            return

        self._heartbeat_server_ready.set()
        poller = zmq.Poller()
        poller.register(sock, zmq.POLLIN)
        try:
            while not self._shutdown_event.is_set():
                if sock in dict(poller.poll(timeout=100)):
                    self._record_heartbeats(sock)
        finally:
            poller.unregister(sock)
            sock.close(linger=0)

    def _record_heartbeats(self, sock: zmq.Socket) -> None:
        """Drena pulsos pendientes y conserva sólo liveness explícita."""
        while True:
            try:
                message = sock.recv(flags=zmq.NOBLOCK)
            except zmq.Again:
                return
            if message == HEARTBEAT:
                self._last_heartbeat = time.monotonic()

    def is_peer_alive(self) -> bool:
        """True sólo si llegó un heartbeat reciente del consumidor."""
        if self.role != "producer" or self._last_heartbeat is None:
            return False
        elapsed_ms = (time.monotonic() - self._last_heartbeat) * 1000.0
        return elapsed_ms <= self.heartbeat_timeout_ms

    def has_seen_peer(self) -> bool:
        """True si el productor ya observó al menos un heartbeat del consumidor."""
        return self.role == "producer" and self._last_heartbeat is not None

    def wait_for_consumer(self, timeout_s: float | None = None) -> bool:
        """Espera a que el consumidor reciba END y el servidor REP termine."""
        if self.role != "producer":
            raise ValueError("wait_for_consumer solo está disponible para el productor.")
        self._server.join(timeout=timeout_s)
        return not self._server.is_alive()

    # --- consumidor ---

    def request(self, **kwargs) -> NormalizedUnit | type[END]:
        self._sock.send(REQUEST)
        data = self._sock.recv()
        if data == END_MSG:
            return END
        return deserialize_unit(data)

    def _send_heartbeats(self) -> None:
        """Emite pulsos desde un socket PUSH que pertenece sólo a este hilo."""
        sock = self._ctx.socket(zmq.PUSH)
        sock.connect(self.heartbeat_endpoint)
        interval_s = self.heartbeat_interval_ms / 1000.0
        try:
            while not self._heartbeat_shutdown_event.is_set():
                try:
                    sock.send(HEARTBEAT, flags=zmq.NOBLOCK)
                except zmq.Again:
                    pass
                self._heartbeat_shutdown_event.wait(interval_s)
        finally:
            sock.close(linger=0)

    def shutdown(self) -> None:
        """Cierra socket y, en producer, espera el hilo servidor."""
        if self.role == "producer":
            self.close()
            self._shutdown_event.set()
            self._server.join(timeout=5.0)
            self._heartbeat_server.join(timeout=5.0)
            return
        self._heartbeat_shutdown_event.set()
        self._heartbeat_thread.join(timeout=5.0)
        self._sock.close(linger=0)

    @property
    def buffer_units_dropped(self) -> int:
        return getattr(self._buffer, "units_dropped", 0) if self.role == "producer" else 0
