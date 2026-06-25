from eovrt_media.config.schemas import TransportConfig
import eovrt_media.transport.factory as factory


def test_transport_compression_defaults():
    t = TransportConfig()
    assert t.compression.codec == "jpeg"
    assert t.compression.quality == 90


def test_create_transport_threads_codec_to_network(monkeypatch):
    captured = {}

    class FakeNet:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(factory, "NetworkTransportAdapter", FakeNet)
    factory.create_transport(
        backend="network",
        role="producer",
        endpoint="tcp://127.0.0.1:5599",
        heartbeat_endpoint="tcp://127.0.0.1:5600",
        codec="jpeg",
        quality=80,
    )
    assert captured["codec"] == "jpeg"
    assert captured["quality"] == 80
