"""Integración loopback de run_node_a / run_node_b (runtime/two_node.py) en el mismo proceso."""
from __future__ import annotations

import json
import socket
import threading
from pathlib import Path

import cv2
import numpy as np

from eovrt_media.config import load_run_config
from eovrt_media.runtime import two_node
from eovrt_media.runtime.two_node import run_node_a, run_node_b


CONFIGS_DIR = Path(__file__).parent / "fixtures"


def _images(folder: Path, count: int = 4) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    for i in range(count):
        cv2.imwrite(
            str(folder / f"img_{i:03d}.jpg"), np.full((48, 64, 3), i * 20, dtype=np.uint8)
        )


def _loopback_endpoint() -> str:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return f"tcp://127.0.0.1:{sock.getsockname()[1]}"


def test_two_node_loopback_produces_detections(tmp_path):
    images = tmp_path / "imgs"
    _images(images, 4)

    cfg = load_run_config(CONFIGS_DIR / "runs" / "mock.yaml")
    cfg.model.adapter = "mock"
    cfg.source.path = str(images)
    cfg.topology.mode = "two_node"
    cfg.transport.backend = "network"
    cfg.transport.endpoint = _loopback_endpoint()
    cfg.transport.heartbeat_endpoint = _loopback_endpoint()
    cfg.outputs.base_dir = str(tmp_path / "runs")
    cfg.outputs.run_dir = str(tmp_path / "runs")
    cfg.outputs.save_previews = False

    node_a = threading.Thread(target=run_node_a, args=(cfg,), daemon=True)
    node_a.start()

    run_id = run_node_b(cfg)
    node_a.join(timeout=10.0)

    assert node_a.is_alive() is False
    detections = (Path(cfg.outputs.base_dir) / run_id / "detections.jsonl").read_text()
    events = [json.loads(line) for line in detections.splitlines()]
    assert len(events) == 4


def test_node_b_starts_transport_before_loading_model(tmp_path, monkeypatch):
    images = tmp_path / "imgs"
    _images(images, 1)

    cfg = load_run_config(CONFIGS_DIR / "runs" / "mock.yaml")
    cfg.model.adapter = "mock"
    cfg.source.path = str(images)
    cfg.topology.mode = "two_node"
    cfg.transport.backend = "network"
    cfg.transport.endpoint = _loopback_endpoint()
    cfg.transport.heartbeat_endpoint = _loopback_endpoint()
    cfg.outputs.base_dir = str(tmp_path / "runs")
    cfg.outputs.run_dir = str(tmp_path / "runs")
    cfg.outputs.save_previews = False

    events: list[str] = []

    class FakeTransport:
        def shutdown(self) -> None:
            events.append("transport.shutdown")

    class FakeAdapter:
        PROMPT_BACKEND = "default"

        def load(self) -> None:
            events.append("adapter.load")
            assert "transport.create" in events

        def close(self) -> None:
            events.append("adapter.close")

    def fake_create_transport(**kwargs):
        events.append("transport.create")
        return FakeTransport()

    def fake_create_adapter(model):
        events.append("adapter.create")
        assert "transport.create" in events
        return FakeAdapter()

    def fake_run_consumer_loop(*args, **kwargs):
        events.append("consumer.loop")

    monkeypatch.setattr("eovrt_media.runtime.two_node.create_transport", fake_create_transport)
    monkeypatch.setattr("eovrt_media.runtime.two_node.create_adapter", fake_create_adapter)
    monkeypatch.setattr("eovrt_media.runtime.two_node.run_consumer_loop", fake_run_consumer_loop)
    monkeypatch.setattr("eovrt_media.runtime.two_node.get_gpu_memory_peak_mb", lambda: 0.0)

    run_node_b(cfg)

    assert events[:4] == ["transport.create", "adapter.create", "adapter.load", "consumer.loop"]


def test_node_a_keeps_waiting_for_end_while_consumer_heartbeat_is_alive():
    class SlowConsumerTransport:
        def __init__(self) -> None:
            self.wait_calls = 0

        def wait_for_consumer(self, timeout_s: float) -> bool:
            self.wait_calls += 1
            return self.wait_calls == 3

        def has_seen_peer(self) -> bool:
            return True

        def is_peer_alive(self) -> bool:
            return True

    transport = SlowConsumerTransport()

    two_node._wait_for_consumer_end(
        transport,
        heartbeat_timeout_ms=5000,
        poll_interval_s=0.0,
    )

    assert transport.wait_calls == 3


def test_node_b_writes_model_load_debug_events(tmp_path, monkeypatch):
    cfg = load_run_config(CONFIGS_DIR / "runs" / "mock.yaml")
    cfg.model.adapter = "mock"
    cfg.topology.mode = "two_node"
    cfg.transport.backend = "network"
    cfg.transport.endpoint = _loopback_endpoint()
    cfg.transport.heartbeat_endpoint = _loopback_endpoint()
    cfg.outputs.base_dir = str(tmp_path / "runs")
    cfg.outputs.run_dir = str(tmp_path / "runs")
    cfg.debug.enabled = True

    events: list[str] = []

    class FakeWriter:
        def __init__(self, context):
            self.context = context

        def write_effective_config(self):
            pass

        def write_debug_event(self, **kwargs):
            events.append(kwargs["event"])

        def close(self):
            pass

        def write_summary(self, tracker):
            pass

        def write_provenance(self):
            pass

        def write_manifest(self):
            pass

    class FakeTransport:
        def shutdown(self):
            pass

    class FakeAdapter:
        PROMPT_BACKEND = "default"

        def load(self):
            pass

        def close(self):
            pass

    monkeypatch.setattr("eovrt_media.runtime.two_node.RunArtifactWriter", FakeWriter)
    monkeypatch.setattr(
        "eovrt_media.runtime.two_node.create_transport",
        lambda **kwargs: FakeTransport(),
    )
    monkeypatch.setattr("eovrt_media.runtime.two_node.create_adapter", lambda model: FakeAdapter())
    monkeypatch.setattr("eovrt_media.runtime.two_node.run_consumer_loop", lambda *args, **kwargs: None)
    monkeypatch.setattr("eovrt_media.runtime.two_node.get_gpu_memory_peak_mb", lambda: 0.0)

    run_node_b(cfg)

    assert "model.load_start" in events
    assert "model.load_end" in events
