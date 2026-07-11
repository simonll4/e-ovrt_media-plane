"""Publicador del bus media->control: envelope `bus.envelope.v1` sobre ZeroMQ (ADR-003).

Reglas no negociables (spec 40 SS3.2):
- No bloquea la inferencia: HWM finito + NOBLOCK; el JSONL es la verdad.
- `seq` es monotonico por publicador y se incrementa AUNQUE el envio se descarte,
  para que el consumidor vea el hueco y marque la corrida degradada.
"""

from __future__ import annotations

import logging
import time

import msgpack
import zmq

logger = logging.getLogger(__name__)

ENVELOPE_SCHEMA_VERSION = "bus.envelope.v1"
DETECTION_TOPIC_PREFIX = "media.detection.v1."
LIFECYCLE_TOPIC_PREFIX = "run.lifecycle.v1."
LIFECYCLE_SCHEMA_VERSION = "run.lifecycle.v1"


def encode_envelope(
    *, topic: str, key: str, seq: int, payload: bytes, ts_publish_ms: float
) -> bytes:
    """Serializa el envelope. `payload` son los bytes del evento tal cual van al JSONL."""
    return msgpack.packb(
        {
            "schema_version": ENVELOPE_SCHEMA_VERSION,
            "topic": topic,
            "key": key,
            "seq": seq,
            "ts_publish_ms": ts_publish_ms,
            "payload": payload,
        },
        use_bin_type=True,
    )


class BusPublisher:
    """Socket XPUB con contador de secuencia por corrida.

    XPUB en vez de PUB: del lado del envio son equivalentes, pero XPUB entrega una
    notificacion cuando un SUB se suscribe, lo que permite implementar la regla de
    "consumidor suscripto antes del disparo" sin dormir a ciegas.

    `send_failures` cuenta unicamente errores de envio (excepciones atrapadas en
    `publish`, por ejemplo `zmq.Again` cuando se alcanza el HWM). NO cuenta las
    perdidas silenciosas de PUB/XPUB: sin `ZMQ_XPUB_NODROP` (que no se activa aqui,
    porque cambiaria la semantica de bloqueo/exito de `send_multipart`), libzmq
    descarta mensajes en silencio al llegar al HWM y `send()` devuelve exito. Medido
    empiricamente con SNDHWM=5 y un SUB que no drena: de 2000 envios con
    `zmq.NOBLOCK`, 0 levantaron `zmq.Again` (`send_failures` habria quedado en 0) pero
    solo 3 mensajes llegaron al suscriptor. La unica senal fiable de perdida es el
    hueco de `seq` que ve el consumidor del lado del bus.
    """

    def __init__(
        self, endpoint: str, *, hwm: int = 1000, wait_for_subscriber_ms: int = 0
    ) -> None:
        self.endpoint = endpoint
        # Contador de errores de envio (no de perdidas por HWM, ver docstring de la clase).
        self.send_failures = 0
        self._seq = 0
        self._closed = False
        self._ctx = zmq.Context.instance()
        self._sock = self._ctx.socket(zmq.XPUB)
        self._sock.setsockopt(zmq.SNDHWM, hwm)
        self._sock.setsockopt(zmq.RCVHWM, 16)
        self._sock.setsockopt(zmq.LINGER, 0)
        self._sock.setsockopt(zmq.XPUB_VERBOSE, 1)
        self._sock.bind(endpoint)
        if wait_for_subscriber_ms > 0:
            self.wait_for_subscriber(wait_for_subscriber_ms)

    def wait_for_subscriber(self, timeout_ms: int, expected: int = 2) -> bool:
        """Espera notificaciones de suscripcion del XPUB (spec 40 SS3.2 regla 1).

        Un consumidor tipico (BusSource del control-plane) hace un SUBSCRIBE por
        cada prefijo de topico que le interesa: uno para deteccion
        (`media.detection.v1.`) y otro para lifecycle (`run.lifecycle.v1.`). XPUB
        entrega una notificacion separada por cada SUBSCRIBE, asi que por default
        se esperan 2 — esperar solo 1 dejaria a la suscripcion de lifecycle sin
        garantia y el `run_finished` podria perderse.

        Drena notificaciones hasta juntar `expected` o hasta que venza el
        `timeout_ms` total (no por notificacion individual). Si el deadline vence
        habiendo drenado menos de `expected`, devuelve False: la corrida sigue
        igual, sin bus (el JSONL es la verdad). Nunca levanta.
        """
        poller = zmq.Poller()
        poller.register(self._sock, zmq.POLLIN)
        deadline = time.monotonic() + timeout_ms / 1000.0
        received = 0
        try:
            while received < expected:
                remaining_ms = (deadline - time.monotonic()) * 1000.0
                if remaining_ms <= 0:
                    break
                if not dict(poller.poll(timeout=remaining_ms)):
                    break
                self._sock.recv()  # b"\x01<topic>"
                received += 1
            if received < expected:
                logger.warning(
                    "bus: %d/%d suscripciones en %d ms; se publica igual "
                    "(el JSONL es la verdad)",
                    received,
                    expected,
                    timeout_ms,
                )
                return False
            return True
        finally:
            poller.unregister(self._sock)

    def publish(self, topic: str, key: str, payload: bytes) -> int:
        """Publica y devuelve el `seq` asignado. Nunca bloquea, nunca levanta hacia el pipeline.

        Si el publicador ya esta cerrado, es un no-op seguro: el `seq` igual se
        consume (el consumidor vera el hueco) pero no se intenta enviar nada.
        Cualquier error de codificacion o de envio (incluido `zmq.Again` por HWM)
        se atrapa y se loguea; nunca se propaga.
        """
        seq = self._seq
        self._seq += 1

        if self._closed:
            logger.debug("bus: publish() sobre publicador cerrado, seq=%d descartado", seq)
            return seq

        try:
            envelope = encode_envelope(
                topic=topic, key=key, seq=seq, payload=payload, ts_publish_ms=time.time() * 1000.0
            )
            self._sock.send_multipart([topic.encode("utf-8"), envelope], flags=zmq.NOBLOCK)
        except zmq.Again:
            # HWM alcanzado. El `seq` ya se consumio: el consumidor vera el hueco.
            self.send_failures += 1
            logger.warning("bus: HWM alcanzado, envelope seq=%d descartado", seq)
        except zmq.ZMQError:
            # Error real de socket (p.ej. socket cerrado bajo carrera, ENOTSOCK).
            self.send_failures += 1
            logger.warning("bus: error de envio, envelope seq=%d descartado", seq, exc_info=True)
        except Exception:
            # Fallo de serializacion (msgpack) u otro error inesperado: nunca escapa.
            self.send_failures += 1
            logger.warning(
                "bus: fallo al codificar/enviar, envelope seq=%d descartado", seq, exc_info=True
            )
        return seq

    def close(self) -> None:
        """Cierra el socket subyacente. Idempotente y nunca levanta hacia el pipeline.

        Si `self._sock.close()` falla, se loguea un warning y el publicador se
        marca como cerrado igual: `publish()` debe seguir siendo el no-op seguro
        que ya es, pase lo que pase con el cierre real del socket.
        """
        if not self._closed:
            try:
                self._sock.close(linger=0)
            except Exception:
                logger.warning("bus: fallo al cerrar el socket", exc_info=True)
            finally:
                self._closed = True
