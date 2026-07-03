from eovrt_media.service.events import EventBroadcaster, EventEmittingArtifactWriter


class _FakeWriter:
    def __init__(self):
        self.calls = []

    def write_metric(self, sample):
        self.calls.append(("metric", sample))

    def write_error(self, event):
        self.calls.append(("error", event))

    def close(self):
        self.calls.append(("close", None))


class _FakeMetric:
    unit_id = "u1"
    fps_effective = 2.0
    latency_total_ms = 500.0
    detections_count = 3
    gpu_memory_allocated_mb = 100.0


class _FakeError:
    unit_id = "u1"
    stage = "inference"
    message = "boom"


def test_writer_delega_y_emite():
    broadcaster = EventBroadcaster()
    sub = broadcaster.subscribe()
    inner = _FakeWriter()
    writer = EventEmittingArtifactWriter(inner, broadcaster)
    writer.write_metric(_FakeMetric())
    writer.write_error(_FakeError())
    writer.close()  # delegado vía __getattr__ o método explícito
    assert [c[0] for c in inner.calls] == ["metric", "error", "close"]
    events = sub.drain()
    types = [e["type"] for e in events]
    assert "metric" in types and "error" in types


def test_subscriber_coalesce_metricas():
    broadcaster = EventBroadcaster()
    sub = broadcaster.subscribe()
    for i in range(5):
        broadcaster.emit({"type": "metric", "unit_id": f"u{i}"})
    broadcaster.emit({"type": "error", "message": "x"})
    events = sub.drain()
    metrics = [e for e in events if e["type"] == "metric"]
    assert len(metrics) == 1 and metrics[0]["unit_id"] == "u4"  # solo la última
    assert len([e for e in events if e["type"] == "error"]) == 1
    assert sub.drain() == []  # drain vacía


def test_last_event_monotonic_avanza():
    broadcaster = EventBroadcaster()
    t0 = broadcaster.last_event_monotonic
    broadcaster.emit({"type": "metric"})
    assert broadcaster.last_event_monotonic >= t0
