import json
import threading
import time

import numpy as np

from eovrt_media.contracts.dropped_unit import build_dropped_record
from eovrt_media.contracts.normalized_unit import (
    NormalizedUnit, ResizeTransform, PayloadFormat,
)
from eovrt_media.contracts.visual_unit import VisualUnit
from eovrt_media.sinks.dropped_units_sink import DroppedUnitsSink
from eovrt_media.transport.memory import MemoryTransportAdapter
import queue as _queue
from types import SimpleNamespace
from eovrt_media.runtime import pipeline as pipeline_mod
from eovrt_media.transport.rate_gate import RateGate


def _visual_unit(frame_index: int = 7) -> VisualUnit:
    return VisualUnit(
        unit_id=f"frame_{frame_index:06d}", source_type="video_frame",
        frame_index=frame_index, timestamp_ms=1234.5, source_clock="media",
        width=640, height=480,
    )


def test_build_dropped_record_carries_full_identity() -> None:
    before = time.time() * 1000.0
    rec = build_dropped_record(_visual_unit(), reason="rate_gate", run_id="run-x")
    assert rec.schema_version == "media.dropped_unit.v1"
    assert (rec.reason, rec.run_id) == ("rate_gate", "run-x")
    assert (rec.unit_id, rec.frame_index) == ("frame_000007", 7)
    assert (rec.timestamp_ms, rec.source_clock) == (1234.5, "media")
    assert rec.dropped_wallclock_ms >= before


def test_build_dropped_record_rejects_unknown_reason() -> None:
    import pytest
    with pytest.raises(ValueError):
        build_dropped_record(_visual_unit(), reason="whatever", run_id="run-x")


def test_sink_lazy_no_file_without_drops(tmp_path) -> None:
    sink = DroppedUnitsSink(tmp_path / "dropped_units.jsonl")
    sink.close()
    assert not (tmp_path / "dropped_units.jsonl").exists()


def test_sink_writes_jsonl_lines(tmp_path) -> None:
    path = tmp_path / "dropped_units.jsonl"
    sink = DroppedUnitsSink(path)
    sink.write(build_dropped_record(_visual_unit(1), "queue_full", "run-x"))
    sink.write(build_dropped_record(_visual_unit(2), "rate_gate", "run-x"))
    sink.close()
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    assert [r["reason"] for r in rows] == ["queue_full", "rate_gate"]


def test_sink_write_after_close_is_noop_does_not_truncate(tmp_path) -> None:
    path = tmp_path / "dropped_units.jsonl"
    sink = DroppedUnitsSink(path)
    sink.write(build_dropped_record(_visual_unit(1), "queue_full", "run-x"))
    sink.write(build_dropped_record(_visual_unit(2), "rate_gate", "run-x"))
    sink.close()
    sink.write(build_dropped_record(_visual_unit(3), "queue_full", "run-x"))
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    assert [r["reason"] for r in rows] == ["queue_full", "rate_gate"]


def test_sink_is_thread_safe(tmp_path) -> None:
    path = tmp_path / "dropped_units.jsonl"
    sink = DroppedUnitsSink(path)

    def spam(n0: int) -> None:
        for i in range(200):
            sink.write(build_dropped_record(_visual_unit(n0 + i), "queue_full", "r"))

    threads = [threading.Thread(target=spam, args=(k * 1000,)) for k in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    sink.close()
    lines = path.read_text().splitlines()
    assert len(lines) == 800
    for line in lines:
        json.loads(line)  # ninguna linea intercalada/corrupta


class _Spy:
    def __init__(self):
        self.calls: list[tuple[str, str]] = []

    def __call__(self, unit, reason: str) -> None:
        self.calls.append((unit.unit_id, reason))


def _norm_unit(i: int, timestamp_ms: float | None = None) -> NormalizedUnit:
    return NormalizedUnit(
        unit_id=f"frame_{i:06d}",
        orig_width=640, orig_height=480,
        payload=np.zeros((640, 640, 3), dtype=np.uint8),
        payload_format=PayloadFormat.UINT8_RGB,
        target_size=(640, 640),
        transform=ResizeTransform(scale_x=1.0, scale_y=1.0, pad_x=0.0, pad_y=0.0),
        timestamp_ms=timestamp_ms if timestamp_ms is not None else float(i) * 10.0,
    )


def test_on_drop_queue_full_bounded_freshness() -> None:
    spy = _Spy()
    t = MemoryTransportAdapter(policy="bounded_freshness", buffer_size=1, on_drop=spy)
    t.offer(_norm_unit(0))
    t.offer(_norm_unit(1))  # desplaza al 0
    assert spy.calls == [("frame_000000", "queue_full")]
    assert t.units_dropped == 1  # el contador NO cambia de semantica


def test_on_drop_staleness_timeout() -> None:
    spy = _Spy()
    t = MemoryTransportAdapter(
        policy="bounded_freshness", buffer_size=2, max_staleness_ms=10.0, on_drop=spy
    )
    t.offer(_norm_unit(0, timestamp_ms=0.0))
    t.close()
    unit = t.request(current_time_ms=lambda: 10_000.0)
    from eovrt_media.contracts.normalized_unit import END
    assert unit is END
    assert spy.calls == [("frame_000000", "staleness_timeout")]


def test_on_drop_channel_closed_deterministic() -> None:
    spy = _Spy()
    t = MemoryTransportAdapter(policy="deterministic", max_queue_size=1, on_drop=spy)
    t.close()
    t.offer(_norm_unit(0))
    assert spy.calls == [("frame_000000", "channel_closed")]


def test_on_drop_none_keeps_behavior() -> None:
    t = MemoryTransportAdapter(policy="bounded_freshness", buffer_size=1)
    t.offer(_norm_unit(0))
    t.offer(_norm_unit(1))
    assert t.units_dropped == 1  # sin callback, todo como antes


class _CollectTransport:
    def __init__(self):
        self.offered = []
    def offer(self, unit):
        self.offered.append(unit)
    def close(self):
        pass


def test_producer_emits_rate_gate_drops(monkeypatch) -> None:
    monkeypatch.setattr(
        pipeline_mod, "normalize_spatial",
        lambda unit, spec, fmt: SimpleNamespace(unit_id=unit.unit_id, run_id=None),
    )
    units = [_visual_unit(i) for i in range(4)]
    spy = _Spy()
    transport = _CollectTransport()
    pipeline_mod.run_producer_loop(
        source=units, rate_gate=RateGate(stride=2), spec=None,
        payload_format=None, transport=transport, run_id="run-x",
        errors_queue=_queue.SimpleQueue(), timings={}, should_continue=None,
        on_drop=spy,
    )
    # stride=2: pasan los indices de enumeracion 0 y 2; se descartan 1 y 3
    assert [u.unit_id for u in transport.offered] == ["frame_000000", "frame_000002"]
    assert spy.calls == [("frame_000001", "rate_gate"), ("frame_000003", "rate_gate")]
