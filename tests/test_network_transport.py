"""NetworkTransportAdapter sobre ZeroMQ en loopback (mismo proceso, dos hilos)."""
from __future__ import annotations

import socket
import threading
import time

import numpy as np
import pytest

from eovrt_media.contracts.normalized_unit import (
    END, NormalizedUnit, PayloadFormat, ResizeTransform,
)
from eovrt_media.config.schemas import TransportConfig
from eovrt_media.transport.factory import create_transport
from eovrt_media.transport.network import NetworkTransportAdapter


def _unit(i: int) -> NormalizedUnit:
    return NormalizedUnit(
        run_id="run_x",
        unit_id=f"frame_{i:06d}",
        source_id="cam0",
        orig_width=64,
        orig_height=48,
        payload=(np.ones((640, 640, 3)) * i).astype(np.uint8),
        payload_format=PayloadFormat.UINT8_RGB,
        target_size=(640, 640),
        transform=ResizeTransform(scale_x=1.0, scale_y=1.0, pad_x=0.0, pad_y=0.0),
    )


@pytest.fixture
def endpoint() -> str:
    # Puerto efímero fijo del rango alto para loopback de test.
    return "tcp://127.0.0.1:5599"


@pytest.fixture
def isolated_endpoint() -> str:
    return _unused_tcp_endpoint()


@pytest.fixture
def heartbeat_endpoint() -> str:
    return _unused_tcp_endpoint()


def _unused_tcp_endpoint() -> str:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    return f"tcp://127.0.0.1:{port}"


def _wait_until(predicate, timeout_s: float = 1.0) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return predicate()


def test_producer_consumer_roundtrip(endpoint, heartbeat_endpoint):
    producer = NetworkTransportAdapter(
        role="producer", endpoint=endpoint, heartbeat_endpoint=heartbeat_endpoint,
        policy="bounded_freshness", buffer_size=8,
    )
    consumer = NetworkTransportAdapter(
        role="consumer", endpoint=endpoint, heartbeat_endpoint=heartbeat_endpoint,
    )

    for i in range(3):
        producer.offer(_unit(i))
    producer.close()

    received = []
    while True:
        item = consumer.request()
        if item is END:
            break
        received.append(item)

    consumer.shutdown()
    producer.shutdown()

    assert [u.unit_id for u in received][:3] == [
        "frame_000000", "frame_000001", "frame_000002",
    ]
    assert received[0].payload.shape == (640, 640, 3)


def test_network_adapter_default_codec_matches_transport_schema(
    isolated_endpoint, heartbeat_endpoint
):
    producer = NetworkTransportAdapter(
        role="producer",
        endpoint=isolated_endpoint,
        heartbeat_endpoint=heartbeat_endpoint,
    )

    assert producer.codec == TransportConfig().compression.codec

    producer.shutdown()


def test_producer_consumer_roundtrip_fp16(isolated_endpoint, heartbeat_endpoint):
    producer = NetworkTransportAdapter(
        role="producer", endpoint=isolated_endpoint, heartbeat_endpoint=heartbeat_endpoint,
        policy="bounded_freshness", buffer_size=2,
    )
    consumer = NetworkTransportAdapter(
        role="consumer", endpoint=isolated_endpoint, heartbeat_endpoint=heartbeat_endpoint,
    )
    payload = np.linspace(0.0, 1.0, 640 * 640 * 3, dtype=np.float16).reshape(640, 640, 3)
    unit = _unit(0).model_copy(
        update={"payload": payload, "payload_format": PayloadFormat.FP16}
    )

    producer.offer(unit)
    producer.close()
    restored = consumer.request()

    consumer.shutdown()
    producer.shutdown()

    assert restored is not END
    assert restored.payload_format == PayloadFormat.FP16
    assert restored.payload.dtype == np.float16
    assert np.allclose(restored.payload, payload, atol=1e-3)


def test_consumer_receives_end_when_buffer_empty_and_closed(endpoint, heartbeat_endpoint):
    producer = NetworkTransportAdapter(
        role="producer", endpoint=endpoint, heartbeat_endpoint=heartbeat_endpoint,
        policy="bounded_freshness", buffer_size=2,
    )
    consumer = NetworkTransportAdapter(
        role="consumer", endpoint=endpoint, heartbeat_endpoint=heartbeat_endpoint,
    )
    producer.close()
    assert consumer.request() is END
    consumer.shutdown()
    producer.shutdown()


def test_invalid_role_raises_value_error(endpoint, heartbeat_endpoint):
    with pytest.raises(ValueError, match="role"):
        NetworkTransportAdapter(
            role="invalid", endpoint=endpoint, heartbeat_endpoint=heartbeat_endpoint,
        )


def test_factory_forwards_heartbeat_settings(endpoint):
    heartbeat_endpoint = _unused_tcp_endpoint()
    producer = create_transport(
        backend="network",
        role="producer",
        endpoint=endpoint,
        heartbeat_endpoint=heartbeat_endpoint,
        heartbeat_interval_ms=250,
        heartbeat_timeout_ms=750,
    )

    assert producer.heartbeat_interval_ms == 250
    assert producer.heartbeat_timeout_ms == 750
    assert producer.heartbeat_endpoint == heartbeat_endpoint

    producer.shutdown()


def test_producer_tracks_dedicated_heartbeat_without_data_requests(isolated_endpoint):
    heartbeat_endpoint = _unused_tcp_endpoint()
    producer = NetworkTransportAdapter(
        role="producer", endpoint=isolated_endpoint, heartbeat_endpoint=heartbeat_endpoint,
        policy="bounded_freshness", buffer_size=4, heartbeat_interval_ms=10,
        heartbeat_timeout_ms=100,
    )
    consumer = NetworkTransportAdapter(
        role="consumer", endpoint=isolated_endpoint, heartbeat_endpoint=heartbeat_endpoint,
        heartbeat_interval_ms=10, heartbeat_timeout_ms=100,
    )

    assert _wait_until(producer.is_peer_alive)

    consumer.shutdown()
    assert _wait_until(lambda: not producer.is_peer_alive(), timeout_s=0.5)
    producer.shutdown()


def test_heartbeat_stays_live_while_data_request_waits_for_a_unit(isolated_endpoint):
    heartbeat_endpoint = _unused_tcp_endpoint()
    producer = NetworkTransportAdapter(
        role="producer", endpoint=isolated_endpoint, heartbeat_endpoint=heartbeat_endpoint,
        policy="bounded_freshness", buffer_size=4, heartbeat_interval_ms=10,
        heartbeat_timeout_ms=100,
    )
    consumer = NetworkTransportAdapter(
        role="consumer", endpoint=isolated_endpoint, heartbeat_endpoint=heartbeat_endpoint,
        heartbeat_interval_ms=10, heartbeat_timeout_ms=100,
    )
    request_thread = threading.Thread(target=consumer.request)
    request_thread.start()

    try:
        assert _wait_until(producer.is_peer_alive, timeout_s=0.5)
    finally:
        producer.close()
        request_thread.join(timeout=1.0)
        consumer.shutdown()
        producer.shutdown()


def test_producer_shutdown_stops_server_after_consumer_stops_early(endpoint, heartbeat_endpoint):
    producer = NetworkTransportAdapter(
        role="producer", endpoint=endpoint, heartbeat_endpoint=heartbeat_endpoint,
        policy="bounded_freshness", buffer_size=4,
    )
    consumer = NetworkTransportAdapter(
        role="consumer", endpoint=endpoint, heartbeat_endpoint=heartbeat_endpoint,
    )

    producer.offer(_unit(0))
    producer.close()
    assert consumer.request().unit_id == "frame_000000"

    consumer.shutdown()
    producer.shutdown()
    consumer.shutdown()
    producer.shutdown()

    assert producer._server.is_alive() is False
    assert producer._heartbeat_server.is_alive() is False
    assert consumer._heartbeat_thread.is_alive() is False


def test_consumer_shutdown_does_not_wait_for_an_unreachable_heartbeat_peer():
    consumer = NetworkTransportAdapter(
        role="consumer",
        endpoint=_unused_tcp_endpoint(),
        heartbeat_endpoint=_unused_tcp_endpoint(),
        heartbeat_interval_ms=1,
    )
    time.sleep(1.2)  # Agota el HWM de PUSH si send() bloquea sin receptor PULL.

    started = time.monotonic()
    consumer.shutdown()

    assert time.monotonic() - started < 1.0
    assert consumer._heartbeat_thread.is_alive() is False


def test_wait_for_consumer_timeout_returns_false_when_no_consumer_requests(
    isolated_endpoint, heartbeat_endpoint
):
    producer = NetworkTransportAdapter(
        role="producer",
        endpoint=isolated_endpoint,
        heartbeat_endpoint=heartbeat_endpoint,
    )
    producer.close()

    started = time.monotonic()
    finished = producer.wait_for_consumer(timeout_s=0.05)

    producer.shutdown()

    assert finished is False
    assert time.monotonic() - started < 0.5
