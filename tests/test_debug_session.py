from __future__ import annotations

import json
from pathlib import Path

import pytest

from eovrt_media.debugging.analyzer import RunAnalysis, Signal
from eovrt_media.debugging.reporter import write_session_report
from eovrt_media.debugging.session import DebugRunOptions, _default_session_dir, run_debug_session


def test_write_session_report_outputs_json_and_markdown(tmp_path: Path) -> None:
    session_dir = tmp_path / "debug-sessions" / "session_x"
    analysis = RunAnalysis(
        run_id="run_raw",
        run_dir="runs/run_raw",
        summary={
            "run_id": "run_raw",
            "units_processed": 5,
            "units_failed": 0,
            "total_detections": 24,
            "p95_latency_ms": 1000,
            "fps_effective": 1.2,
        },
        signals=[
            Signal(
                severity="warning",
                code="P95_LATENCY_HIGH",
                message="p95 latency is high",
                evidence={"p95_latency_ms": 1000},
                suggestion="Inspect metrics.",
            )
        ],
    )

    result = write_session_report(
        session_dir=session_dir,
        session_config={"source": "bench-val", "codecs": ["raw"]},
        analyses=[analysis],
        runs=[{"codec": "raw", "run_id": "run_raw", "run_dir": "runs/run_raw"}],
    )

    assert result.json_path == session_dir / "session_report.json"
    assert result.markdown_path == session_dir / "session_report.md"
    payload = json.loads(result.json_path.read_text(encoding="utf-8"))
    assert payload["session_config"]["source"] == "bench-val"
    assert payload["analyses"][0]["run_id"] == "run_raw"
    markdown = result.markdown_path.read_text(encoding="utf-8")
    assert "run_raw" in markdown
    assert "P95_LATENCY_HIGH" in markdown


def test_run_debug_session_executes_one_run_per_codec(tmp_path: Path, monkeypatch) -> None:
    calls = []

    class FakeLocalResult:
        ok = True
        config_path = tmp_path / "generated.yaml"
        logs_dir = tmp_path / "logs"
        node_a_log = tmp_path / "logs" / "node-a.log"
        node_b_log = tmp_path / "logs" / "node-b.log"
        run_dir = tmp_path / "runs" / "run_x"
        node_a_returncode = 0
        node_b_returncode = 0
        summary = {"run_id": "run_x"}
        warnings = []
        failure_reason = ""

    def fake_run_two_node_local(options):
        calls.append(options.codec)
        FakeLocalResult.config_path.write_text("run: {}\n", encoding="utf-8")
        FakeLocalResult.node_a_log.parent.mkdir(parents=True, exist_ok=True)
        FakeLocalResult.node_a_log.write_text("", encoding="utf-8")
        FakeLocalResult.node_b_log.write_text("", encoding="utf-8")
        FakeLocalResult.run_dir.mkdir(parents=True, exist_ok=True)
        (FakeLocalResult.run_dir / "summary.json").write_text(
            '{"run_id":"run_x","units_processed":1,"units_failed":0,"units_dropped":0,'
            '"p95_latency_ms":1,"p99_latency_ms":1,"backpressure_wait_ms":0,'
            '"gpu_memory_peak_mb":0,"total_detections":1}',
            encoding="utf-8",
        )
        (FakeLocalResult.run_dir / "debug_events.jsonl").write_text("{}\n", encoding="utf-8")
        return FakeLocalResult()

    monkeypatch.setattr("eovrt_media.debugging.session.run_two_node_local", fake_run_two_node_local)

    result = run_debug_session(
        DebugRunOptions(
            source="bench-val",
            model_ref="mock",
            device="cpu",
            codecs=["raw", "jpeg"],
            max_units=1,
            debug=True,
            session_dir=tmp_path / "session",
        )
    )

    assert calls == ["raw", "jpeg"]
    assert result.session_dir == tmp_path / "session"
    assert result.report_json.exists()
    assert result.report_markdown.exists()


def test_run_debug_session_allows_config_already_in_generated_dir(
    tmp_path: Path, monkeypatch
) -> None:
    session_dir = tmp_path / "session"
    generated_config_path = session_dir / "generated-configs" / "bench_val_raw.yaml"
    duplicate_config_path = session_dir / "generated-configs" / "bench-val_raw.yaml"

    class FakeLocalResult:
        ok = True
        logs_dir = session_dir / "logs"
        node_a_log = logs_dir / "node-a.log"
        node_b_log = logs_dir / "node-b.log"
        run_dir = tmp_path / "runs" / "run_x"
        node_a_returncode = 0
        node_b_returncode = 0
        summary = {"run_id": "run_x"}
        warnings = []
        failure_reason = ""
        config_path = generated_config_path

    def fake_run_two_node_local(options):
        generated_config_path.parent.mkdir(parents=True, exist_ok=True)
        generated_config_path.write_text("run: {}\n", encoding="utf-8")
        FakeLocalResult.node_a_log.parent.mkdir(parents=True, exist_ok=True)
        FakeLocalResult.node_a_log.write_text("", encoding="utf-8")
        FakeLocalResult.node_b_log.write_text("", encoding="utf-8")
        FakeLocalResult.run_dir.mkdir(parents=True, exist_ok=True)
        (FakeLocalResult.run_dir / "summary.json").write_text(
            '{"run_id":"run_x","units_processed":1,"units_failed":0,"units_dropped":0,'
            '"p95_latency_ms":1,"p99_latency_ms":1,"backpressure_wait_ms":0,'
            '"gpu_memory_peak_mb":0,"total_detections":1}',
            encoding="utf-8",
        )
        (FakeLocalResult.run_dir / "debug_events.jsonl").write_text("{}\n", encoding="utf-8")
        return FakeLocalResult()

    monkeypatch.setattr("eovrt_media.debugging.session.run_two_node_local", fake_run_two_node_local)

    result = run_debug_session(
        DebugRunOptions(
            source="bench-val",
            model_ref="mock",
            device="cpu",
            codecs=["raw"],
            max_units=1,
            debug=True,
            session_dir=session_dir,
        )
    )

    assert result.report_json.exists()
    assert result.runs[0]["config"] == str(generated_config_path)
    assert duplicate_config_path.exists() is False


def test_run_debug_session_reports_failed_run_without_run_dir(
    tmp_path: Path, monkeypatch
) -> None:
    session_dir = tmp_path / "session"
    generated_config_path = session_dir / "generated-configs" / "bench_val_raw.yaml"

    class FakeLocalResult:
        ok = False
        logs_dir = session_dir / "logs"
        node_a_log = logs_dir / "node-a.log"
        node_b_log = logs_dir / "node-b.log"
        run_dir = None
        node_a_returncode = 0
        node_b_returncode = 1
        summary = {}
        warnings = ["Traceback in node B"]
        failure_reason = "Nodo B exited with code 1"
        config_path = generated_config_path

    def fake_run_two_node_local(options):
        generated_config_path.parent.mkdir(parents=True, exist_ok=True)
        generated_config_path.write_text("run: {}\n", encoding="utf-8")
        FakeLocalResult.node_a_log.parent.mkdir(parents=True, exist_ok=True)
        FakeLocalResult.node_a_log.write_text("", encoding="utf-8")
        FakeLocalResult.node_b_log.write_text("Traceback in node B\n", encoding="utf-8")
        return FakeLocalResult()

    monkeypatch.setattr("eovrt_media.debugging.session.run_two_node_local", fake_run_two_node_local)

    result = run_debug_session(
        DebugRunOptions(
            source="bench-val",
            model_ref="mock",
            device="cpu",
            codecs=["raw"],
            max_units=1,
            debug=True,
            session_dir=session_dir,
        )
    )

    assert result.runs[0]["ok"] is False
    assert result.runs[0]["run_id"] == "failed_raw"
    assert result.analyses[0].signals[0].code == "LOCAL_RUN_FAILED"
    markdown = result.report_markdown.read_text(encoding="utf-8")
    assert "LOCAL_RUN_FAILED" in markdown
    assert "Nodo B exited with code 1" in markdown


def test_default_session_dir_is_unique_and_readable() -> None:
    options = DebugRunOptions(source="bench-val", model_ref="mock")

    first = _default_session_dir(options)
    second = _default_session_dir(options)

    assert first != second
    assert first.parent == second.parent
    assert first.name.startswith("bench-val_mock_")


def test_run_debug_session_requires_at_least_one_codec(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="al menos un codec"):
        run_debug_session(
            DebugRunOptions(
                source="bench-val",
                model_ref="mock",
                device="cpu",
                codecs=[],
                session_dir=tmp_path / "session",
            )
        )
