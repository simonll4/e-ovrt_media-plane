from __future__ import annotations

import json
from pathlib import Path

from eovrt_media.debugging.analyzer import Signal, analyze_run


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def test_analyze_run_reports_missing_summary(tmp_path: Path) -> None:
    run_dir = tmp_path / "runs" / "run_missing"
    run_dir.mkdir(parents=True)

    result = analyze_run(run_dir=run_dir, node_logs=[], debug_expected=True)

    assert result.run_id == "run_missing"
    assert any(signal.code == "RUN_SUMMARY_MISSING" for signal in result.signals)


def test_analyze_run_detects_errors_latency_and_log_traceback(tmp_path: Path) -> None:
    run_dir = tmp_path / "runs" / "run_x"
    _write_json(
        run_dir / "summary.json",
        {
            "run_id": "run_x",
            "units_processed": 10,
            "units_failed": 1,
            "units_dropped": 2,
            "errors_count": 1,
            "p95_latency_ms": 2500,
            "p99_latency_ms": 3500,
            "backpressure_wait_ms": 11.5,
            "gpu_memory_peak_mb": 7100,
            "total_detections": 20,
        },
    )
    (run_dir / "errors.jsonl").write_text('{"stage":"inference"}\n', encoding="utf-8")
    (run_dir / "debug_events.jsonl").write_text('{"event":"x"}\n', encoding="utf-8")
    log = tmp_path / "node-b.log"
    log.write_text("Traceback in model load\n", encoding="utf-8")

    result = analyze_run(run_dir=run_dir, node_logs=[log], debug_expected=True)
    codes = {signal.code for signal in result.signals}

    assert "UNITS_FAILED" in codes
    assert "ERRORS_JSONL_NONEMPTY" in codes
    assert "P95_LATENCY_HIGH" in codes
    assert "P99_LATENCY_HIGH" in codes
    assert "UNITS_DROPPED" in codes
    assert "BACKPRESSURE_OBSERVED" in codes
    assert "GPU_MEMORY_HIGH" in codes
    assert "LOG_HAS_ERROR" in codes


def test_analyze_run_warns_when_debug_expected_but_missing(tmp_path: Path) -> None:
    run_dir = tmp_path / "runs" / "run_x"
    _write_json(
        run_dir / "summary.json",
        {
            "run_id": "run_x",
            "units_processed": 1,
            "units_failed": 0,
            "units_dropped": 0,
            "p95_latency_ms": 1,
            "p99_latency_ms": 1,
            "backpressure_wait_ms": 0,
            "gpu_memory_peak_mb": 0,
            "total_detections": 1,
        },
    )

    result = analyze_run(run_dir=run_dir, node_logs=[], debug_expected=True)

    assert any(signal.code == "DEBUG_EVENTS_MISSING" for signal in result.signals)


def test_signal_is_serializable() -> None:
    signal = Signal(
        severity="warning",
        code="P95_LATENCY_HIGH",
        message="p95 latency is high",
        evidence={"p95_latency_ms": 2500},
        suggestion="Inspect inference timings.",
    )

    assert signal.model_dump()["code"] == "P95_LATENCY_HIGH"
