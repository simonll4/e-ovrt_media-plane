import socket

import msgpack
import pytest
import zmq

from eovrt_media.transport.bus import (
    DETECTION_TOPIC_PREFIX,
    ENVELOPE_SCHEMA_VERSION,
    LIFECYCLE_TOPIC_PREFIX,
    BusPublisher,
    encode_envelope,
)


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def test_encode_envelope_has_exactly_the_spec_fields() -> None:
    raw = encode_envelope(
        topic="media.detection.v1.run-1",
        key="cam-1",
        seq=7,
        payload=b'{"a": 1}',
        ts_publish_ms=1234.5,
    )

    envelope = msgpack.unpackb(raw, raw=False)

    assert set(envelope) == {
        "schema_version",
        "topic",
        "key",
        "seq",
        "ts_publish_ms",
        "payload",
    }
    assert envelope["schema_version"] == ENVELOPE_SCHEMA_VERSION
    assert envelope["seq"] == 7
    # El payload viaja como bytes crudos, byte-compatible con la linea JSONL.
    assert envelope["payload"] == b'{"a": 1}'


@pytest.fixture()
def publisher_and_subscriber():
    endpoint = f"tcp://127.0.0.1:{_free_port()}"
    publisher = BusPublisher(endpoint, hwm=100)
    context = zmq.Context.instance()
    subscriber = context.socket(zmq.SUB)
    # Dos SUBSCRIBE, como un consumidor real (BusSource del control-plane): uno
    # por prefijo de interes. XPUB entrega una notificacion por cada uno, asi
    # que el wait_for_subscriber(expected=2 por default) de abajo espera las dos.
    subscriber.setsockopt_string(zmq.SUBSCRIBE, DETECTION_TOPIC_PREFIX)
    subscriber.setsockopt_string(zmq.SUBSCRIBE, LIFECYCLE_TOPIC_PREFIX)
    subscriber.connect(endpoint)
    # XPUB avisa cuando las suscripciones llegaron: cierra la ventana de slow joiner.
    assert publisher.wait_for_subscriber(3000) is True
    yield publisher, subscriber
    subscriber.close(linger=0)
    publisher.close()


def test_publish_delivers_envelope_to_a_real_subscriber(publisher_and_subscriber) -> None:
    publisher, subscriber = publisher_and_subscriber

    publisher.publish("media.detection.v1.run-1", "cam-1", b'{"unit_id": "u1"}')

    topic, raw = subscriber.recv_multipart()
    envelope = msgpack.unpackb(raw, raw=False)
    assert topic == b"media.detection.v1.run-1"
    assert envelope["key"] == "cam-1"
    assert envelope["payload"] == b'{"unit_id": "u1"}'


def test_seq_starts_at_zero_and_is_monotonic(publisher_and_subscriber) -> None:
    publisher, subscriber = publisher_and_subscriber

    seqs = [publisher.publish("media.detection.v1.run-1", "cam-1", b"{}") for _ in range(3)]

    assert seqs == [0, 1, 2]
    received = [
        msgpack.unpackb(subscriber.recv_multipart()[1], raw=False)["seq"] for _ in range(3)
    ]
    assert received == [0, 1, 2]


def test_publish_after_close_does_not_raise_and_still_consumes_seq() -> None:
    publisher = BusPublisher(f"tcp://127.0.0.1:{_free_port()}", hwm=10)
    publisher.close()

    # No debe levantar (Hallazgo 1): sobre un publicador cerrado, publish() es un
    # no-op seguro. El seq se sigue consumiendo para que el consumidor vea el hueco.
    seq0 = publisher.publish("media.detection.v1.run-1", "cam-1", b"{}")
    seq1 = publisher.publish("media.detection.v1.run-1", "cam-1", b"{}")

    assert [seq0, seq1] == [0, 1]


def test_close_never_raises_even_if_the_underlying_socket_close_fails(monkeypatch) -> None:
    publisher = BusPublisher(f"tcp://127.0.0.1:{_free_port()}", hwm=10)

    def _boom(*args, **kwargs):
        raise zmq.ZMQError(msg="cierre de socket simulado que falla")

    monkeypatch.setattr(publisher._sock, "close", _boom)

    # No debe levantar (Hallazgo 1): close() es idempotente y a prueba de fallos.
    publisher.close()

    # El publicador queda marcado como cerrado igual: publish() sigue siendo el
    # no-op seguro de siempre, consumiendo el seq sin intentar enviar nada.
    seq0 = publisher.publish("media.detection.v1.run-1", "cam-1", b"{}")
    seq1 = publisher.publish("media.detection.v1.run-1", "cam-1", b"{}")

    assert [seq0, seq1] == [0, 1]


def test_wait_for_subscriber_times_out_without_blocking_the_run() -> None:
    publisher = BusPublisher(f"tcp://127.0.0.1:{_free_port()}", hwm=10)
    try:
        # Sin suscriptor: devuelve False y la corrida sigue (el JSONL es la verdad).
        assert publisher.wait_for_subscriber(50) is False
        assert publisher.publish("media.detection.v1.run-1", "cam-1", b"{}") == 0
    finally:
        publisher.close()


def test_wait_for_subscriber_returns_false_when_fewer_notifications_than_expected() -> None:
    """Hallazgo 2: un consumidor real hace un SUBSCRIBE por prefijo de interes
    (deteccion + lifecycle) y XPUB entrega una notificacion por cada uno. Si
    solo se suscribe a UN prefijo, llega una sola notificacion; con el
    `expected=2` por default eso es menos de lo esperado: debe agotar el
    timeout, no levantar, y la corrida debe poder seguir igual.
    """
    endpoint = f"tcp://127.0.0.1:{_free_port()}"
    publisher = BusPublisher(endpoint, hwm=10)
    context = zmq.Context.instance()
    subscriber = context.socket(zmq.SUB)
    subscriber.setsockopt_string(zmq.SUBSCRIBE, DETECTION_TOPIC_PREFIX)  # solo UNA suscripcion
    subscriber.connect(endpoint)
    try:
        assert publisher.wait_for_subscriber(300, expected=2) is False
        # La corrida sigue igual: publish() no se ve afectado por el False.
        assert publisher.publish("media.detection.v1.run-1", "cam-1", b"{}") == 0
    finally:
        subscriber.close(linger=0)
        publisher.close()


def test_wait_for_subscriber_accepts_a_custom_expected_count() -> None:
    """El default es 2 (deteccion + lifecycle), pero un consumidor que solo le
    interesa un topico puede pedir `expected=1` explicitamente."""
    endpoint = f"tcp://127.0.0.1:{_free_port()}"
    publisher = BusPublisher(endpoint, hwm=10)
    context = zmq.Context.instance()
    subscriber = context.socket(zmq.SUB)
    subscriber.setsockopt_string(zmq.SUBSCRIBE, DETECTION_TOPIC_PREFIX)
    subscriber.connect(endpoint)
    try:
        assert publisher.wait_for_subscriber(3000, expected=1) is True
    finally:
        subscriber.close(linger=0)
        publisher.close()
