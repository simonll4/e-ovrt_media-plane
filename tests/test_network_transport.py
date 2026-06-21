"""NetworkTransportAdapter sobre ZeroMQ en loopback (mismo proceso, dos hilos)."""
from __future__ import annotations

import numpy as np
import pytest

from eovrt_media.contracts.normalized_unit import (
    END, NormalizedUnit, PayloadFormat, ResizeTransform,
)
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


def test_producer_consumer_roundtrip(endpoint):
    producer = NetworkTransportAdapter(
        role="producer", endpoint=endpoint, policy="bounded_freshness", buffer_size=8
    )
    consumer = NetworkTransportAdapter(role="consumer", endpoint=endpoint)

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


def test_consumer_receives_end_when_buffer_empty_and_closed(endpoint):
    producer = NetworkTransportAdapter(
        role="producer", endpoint=endpoint, policy="bounded_freshness", buffer_size=2
    )
    consumer = NetworkTransportAdapter(role="consumer", endpoint=endpoint)
    producer.close()
    assert consumer.request() is END
    consumer.shutdown()
    producer.shutdown()


def test_invalid_role_raises_value_error(endpoint):
    with pytest.raises(ValueError, match="role"):
        NetworkTransportAdapter(role="invalid", endpoint=endpoint)


def test_factory_forwards_heartbeat_settings(endpoint):
    producer = create_transport(
        backend="network",
        role="producer",
        endpoint=endpoint,
        heartbeat_interval_ms=250,
        heartbeat_timeout_ms=750,
    )

    assert producer.heartbeat_interval_ms == 250
    assert producer.heartbeat_timeout_ms == 750

    producer.shutdown()


def test_producer_tracks_peer_activity(endpoint):
    producer = NetworkTransportAdapter(
        role="producer", endpoint=endpoint, policy="bounded_freshness",
        buffer_size=4, heartbeat_timeout_ms=10_000,
    )
    consumer = NetworkTransportAdapter(role="consumer", endpoint=endpoint)

    producer.offer(_unit(0))
    producer.close()
    _ = consumer.request()       # consume el frame → actividad registrada
    assert producer.is_peer_alive() is True

    consumer.shutdown()
    producer.shutdown()


def test_producer_shutdown_stops_server_after_consumer_stops_early(endpoint):
    producer = NetworkTransportAdapter(
        role="producer", endpoint=endpoint, policy="bounded_freshness", buffer_size=4
    )
    consumer = NetworkTransportAdapter(role="consumer", endpoint=endpoint)

    producer.offer(_unit(0))
    producer.close()
    assert consumer.request().unit_id == "frame_000000"

    consumer.shutdown()
    producer.shutdown()

    assert producer._server.is_alive() is False
