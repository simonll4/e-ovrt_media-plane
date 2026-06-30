# Media Plane Debug Framework Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Build a v1 debug framework that runs local media-plane debug campaigns, emits structured per-run debug events, analyzes run artifacts, and writes JSON/Markdown session reports.

**Architecture:** Add a focused `eovrt_media.debugging` package for debug event contracts, JSONL writing, run analysis, session reporting, and campaign orchestration. Integrate the existing `run-two-node-local` bench by adding debug-related options and session directories, then expose a new `eovrt-media debug-run` CLI command. The first instrumentation pass should be useful but conservative: wrapper/process/session events plus run-level debug event files, with deeper runtime/transport events added after the analyzer/reporting loop is working.

**Tech Stack:** Python 3.11+, Typer, Pydantic, PyYAML, JSONL files, pytest, Ruff, existing media-plane run artifacts.

---

## Working Rules

- Do not create commits. The user will commit manually after validating the system.
- Preserve existing uncommitted fixes in `src/eovrt_media/runtime/two_node.py`, `src/eovrt_media/runtime/two_node_local.py`, `tests/test_cli_two_node.py`, and `tests/test_two_node_local.py`.
- Use TDD for behavior changes: write failing tests, watch them fail, implement, verify.
- Keep v1 CLI sequential. Do not introduce parallel matrix execution.

## File Structure

- Create `src/eovrt_media/debugging/__init__.py`: public exports.
- Create `src/eovrt_media/debugging/events.py`: `DebugEvent` schema and `DebugEventWriter`.
- Create `src/eovrt_media/debugging/analyzer.py`: artifact readers and signal detection.
- Create `src/eovrt_media/debugging/reporter.py`: `session_report.json` and `session_report.md`.
- Create `src/eovrt_media/debugging/session.py`: `DebugRunOptions`, `DebugSessionResult`, and `run_debug_session`.
- Modify `src/eovrt_media/runtime/two_node_local.py`: add debug/session options, wrapper debug event emission, and session log/config destinations.
- Modify `src/eovrt_media/cli.py`: add `debug-run`.
- Create `tests/test_debug_events.py`.
- Create `tests/test_debug_analyzer.py`.
- Create `tests/test_debug_session.py`.
- Create `tests/test_cli_debug_run.py`.
- Modify `docs/usage.md`: document debug-run after the native two-node bench section.

## Task 1: Debug Event Contract And Writer

**Files:**
- Create: `src/eovrt_media/debugging/__init__.py`
- Create: `src/eovrt_media/debugging/events.py`
- Test: `tests/test_debug_events.py`

- [x] **Step 1: Write failing tests**

Create `tests/test_debug_events.py`:

```python
from __future__ import annotations

import json
from pathlib import Path

from eovrt_media.debugging.events import DebugEvent, DebugEventWriter


def test_debug_event_defaults_and_json_roundtrip() -> None:
    event = DebugEvent(
        run_id="run_x",
        node="B",
        stage="model",
        event="load_start",
        device="cuda:0",
        extra={"model": "yoloe-26s"},
    )

    raw = event.model_dump(mode="json")

    assert raw["schema_version"] == "media.debug.v1"
    assert raw["run_id"] == "run_x"
    assert raw["node"] == "B"
    assert raw["stage"] == "model"
    assert raw["event"] == "load_start"
    assert raw["device"] == "cuda:0"
    assert raw["extra"] == {"model": "yoloe-26s"}
    assert "T" in raw["ts"]


def test_debug_event_writer_writes_jsonl(tmp_path: Path) -> None:
    path = tmp_path / "debug_events.jsonl"
    writer = DebugEventWriter(path, enabled=True)

    writer.write(
        run_id="run_x",
        node="A",
        stage="transport",
        event="offer",
        unit_id="frame_001",
        payload_bytes=123,
        codec="jpeg",
    )
    writer.close()

    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    payload = json.loads(lines[0])
    assert payload["run_id"] == "run_x"
    assert payload["payload_bytes"] == 123
    assert payload["codec"] == "jpeg"


def test_debug_event_writer_noop_when_disabled(tmp_path: Path) -> None:
    path = tmp_path / "debug_events.jsonl"
    writer = DebugEventWriter(path, enabled=False)

    writer.write(run_id="run_x", node="session", stage="process", event="start")
    writer.close()

    assert path.exists() is False
```

- [x] **Step 2: Verify red**

Run: `source .venv/bin/activate && pytest tests/test_debug_events.py -v`

Expected: FAIL with `ModuleNotFoundError: No module named 'eovrt_media.debugging'`.

- [x] **Step 3: Implement minimal event contract and writer**

Create `src/eovrt_media/debugging/events.py`:

```python
"""Structured debug events for media-plane diagnostic runs."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field


DebugNode = Literal["A", "B", "session", "single_host", "transport"]


class DebugEvent(BaseModel):
    """One structured diagnostic event."""

    schema_version: str = "media.debug.v1"
    ts: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    run_id: str | None = None
    node: DebugNode
    stage: str
    event: str
    unit_id: str | None = None
    elapsed_ms: float | None = None
    payload_bytes: int | None = None
    codec: str | None = None
    device: str | None = None
    message: str | None = None
    extra: dict[str, Any] = Field(default_factory=dict)


class DebugEventWriter:
    """Append JSONL debug events, or act as a no-op when disabled."""

    def __init__(self, path: Path, *, enabled: bool) -> None:
        self.path = path
        self.enabled = enabled
        self._file = None
        if enabled:
            path.parent.mkdir(parents=True, exist_ok=True)
            self._file = path.open("a", encoding="utf-8")

    def write(self, **kwargs: Any) -> None:
        if not self.enabled or self._file is None:
            return
        event = DebugEvent(**kwargs)
        self._file.write(event.model_dump_json(exclude_none=True) + "\n")
        self._file.flush()

    def close(self) -> None:
        if self._file is not None:
            self._file.close()
            self._file = None
```

Create `src/eovrt_media/debugging/__init__.py`:

```python
"""Debugging framework for media-plane diagnostic campaigns."""

from eovrt_media.debugging.events import DebugEvent, DebugEventWriter

__all__ = ["DebugEvent", "DebugEventWriter"]
```

- [x] **Step 4: Verify green**

Run: `source .venv/bin/activate && pytest tests/test_debug_events.py -v`

Expected: PASS.

- [x] **Step 5: Checkpoint**

Run: `git diff -- src/eovrt_media/debugging/events.py tests/test_debug_events.py`

Expected: diff contains only event schema/writer and tests. Do not commit.

## Task 2: Run Analyzer And Signals

**Files:**
- Create: `src/eovrt_media/debugging/analyzer.py`
- Test: `tests/test_debug_analyzer.py`

- [x] **Step 1: Write failing analyzer tests**

Create `tests/test_debug_analyzer.py`:

```python
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
```

- [x] **Step 2: Verify red**

Run: `source .venv/bin/activate && pytest tests/test_debug_analyzer.py -v`

Expected: FAIL with `ModuleNotFoundError` or missing `analyzer`.

- [x] **Step 3: Implement analyzer**

Create `src/eovrt_media/debugging/analyzer.py`:

```python
"""Analyze media-plane run artifacts and emit diagnostic signals."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field


Severity = Literal["info", "warning", "error"]


class Signal(BaseModel):
    severity: Severity
    code: str
    message: str
    evidence: dict[str, Any] = Field(default_factory=dict)
    suggestion: str


class RunAnalysis(BaseModel):
    run_id: str
    run_dir: str
    summary: dict[str, Any] = Field(default_factory=dict)
    signals: list[Signal] = Field(default_factory=list)


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _count_lines(path: Path) -> int:
    if not path.exists():
        return 0
    return len(path.read_text(encoding="utf-8").splitlines())


def _log_error_lines(paths: list[Path]) -> list[str]:
    lines: list[str] = []
    for path in paths:
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            lowered = line.lower()
            if "warning" in lowered or "error" in lowered or "traceback" in lowered:
                lines.append(f"{path}: {line}")
    return lines


def analyze_run(
    *,
    run_dir: Path,
    node_logs: list[Path],
    debug_expected: bool,
    p95_threshold_ms: float = 2000,
    p99_threshold_ms: float = 3000,
    gpu_memory_threshold_mb: float = 7000,
) -> RunAnalysis:
    summary = _read_json(run_dir / "summary.json")
    run_id = str(summary.get("run_id") or run_dir.name)
    signals: list[Signal] = []

    if not summary:
        signals.append(
            Signal(
                severity="error",
                code="RUN_SUMMARY_MISSING",
                message="summary.json is missing or empty.",
                evidence={"run_dir": str(run_dir)},
                suggestion="Inspect node logs and process return codes.",
            )
        )
        return RunAnalysis(run_id=run_id, run_dir=str(run_dir), summary={}, signals=signals)

    if int(summary.get("units_failed") or 0) > 0:
        signals.append(
            Signal(
                severity="error",
                code="UNITS_FAILED",
                message="At least one unit failed.",
                evidence={"units_failed": summary.get("units_failed")},
                suggestion="Inspect errors.jsonl and stage-specific debug events.",
            )
        )

    errors_count = _count_lines(run_dir / "errors.jsonl")
    if errors_count > 0:
        signals.append(
            Signal(
                severity="error",
                code="ERRORS_JSONL_NONEMPTY",
                message="errors.jsonl contains recoverable errors.",
                evidence={"errors_count": errors_count},
                suggestion="Group errors by stage and fix the highest-frequency stage first.",
            )
        )

    p95 = float(summary.get("p95_latency_ms") or 0)
    if p95 > p95_threshold_ms:
        signals.append(
            Signal(
                severity="warning",
                code="P95_LATENCY_HIGH",
                message="p95 latency is above threshold.",
                evidence={"p95_latency_ms": p95, "threshold_ms": p95_threshold_ms},
                suggestion="Compare inference_ms and normalize_ms in metrics.jsonl.",
            )
        )

    p99 = float(summary.get("p99_latency_ms") or 0)
    if p99 > p99_threshold_ms:
        signals.append(
            Signal(
                severity="warning",
                code="P99_LATENCY_HIGH",
                message="p99 latency is above threshold.",
                evidence={"p99_latency_ms": p99, "threshold_ms": p99_threshold_ms},
                suggestion="Inspect slowest per-unit metrics and model warmup behavior.",
            )
        )

    dropped = int(summary.get("units_dropped") or 0)
    if dropped > 0:
        signals.append(
            Signal(
                severity="warning",
                code="UNITS_DROPPED",
                message="Units were dropped by rate control or transport buffering.",
                evidence={"units_dropped": dropped},
                suggestion="Inspect bounded_freshness settings and consumer throughput.",
            )
        )

    backpressure = float(summary.get("backpressure_wait_ms") or 0)
    if backpressure > 0:
        signals.append(
            Signal(
                severity="info",
                code="BACKPRESSURE_OBSERVED",
                message="Producer observed backpressure.",
                evidence={"backpressure_wait_ms": backpressure},
                suggestion="Compare producer normalization time against consumer inference time.",
            )
        )

    gpu_peak = float(summary.get("gpu_memory_peak_mb") or 0)
    if gpu_peak > gpu_memory_threshold_mb:
        signals.append(
            Signal(
                severity="warning",
                code="GPU_MEMORY_HIGH",
                message="GPU peak memory is high.",
                evidence={"gpu_memory_peak_mb": gpu_peak, "threshold_mb": gpu_memory_threshold_mb},
                suggestion="Reduce image size, model variant, or batch-like concurrency.",
            )
        )

    log_lines = _log_error_lines(node_logs)
    if log_lines:
        signals.append(
            Signal(
                severity="error",
                code="LOG_HAS_ERROR",
                message="Node logs contain warnings, errors, or tracebacks.",
                evidence={"lines": log_lines[:20]},
                suggestion="Inspect full node logs before trusting the run.",
            )
        )

    if debug_expected and not (run_dir / "debug_events.jsonl").exists():
        signals.append(
            Signal(
                severity="warning",
                code="DEBUG_EVENTS_MISSING",
                message="Debug mode was expected but debug_events.jsonl is missing.",
                evidence={"run_dir": str(run_dir)},
                suggestion="Verify debug options are propagated into the run config and writer.",
            )
        )

    return RunAnalysis(run_id=run_id, run_dir=str(run_dir), summary=summary, signals=signals)
```

- [x] **Step 4: Verify green**

Run: `source .venv/bin/activate && pytest tests/test_debug_analyzer.py -v`

Expected: PASS.

- [x] **Step 5: Checkpoint**

Run: `source .venv/bin/activate && ruff check src/eovrt_media/debugging tests/test_debug_analyzer.py`

Expected: PASS. Do not commit.

## Task 3: Session Reporter

**Files:**
- Create: `src/eovrt_media/debugging/reporter.py`
- Test: `tests/test_debug_session.py`

- [x] **Step 1: Write failing reporter tests**

Create `tests/test_debug_session.py`:

```python
from __future__ import annotations

import json
from pathlib import Path

from eovrt_media.debugging.analyzer import RunAnalysis, Signal
from eovrt_media.debugging.reporter import write_session_report


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
```

- [x] **Step 2: Verify red**

Run: `source .venv/bin/activate && pytest tests/test_debug_session.py -v`

Expected: FAIL with missing `reporter`.

- [x] **Step 3: Implement reporter**

Create `src/eovrt_media/debugging/reporter.py`:

```python
"""Session report writers for debug campaigns."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from eovrt_media.debugging.analyzer import RunAnalysis


@dataclass(frozen=True)
class SessionReportResult:
    json_path: Path
    markdown_path: Path


def _severity_rank(severity: str) -> int:
    return {"error": 0, "warning": 1, "info": 2}.get(severity, 3)


def _markdown(session_config: dict[str, Any], analyses: list[RunAnalysis]) -> str:
    lines = [
        "# Media Plane Debug Session",
        "",
        "## Config",
        "",
        "```json",
        json.dumps(session_config, indent=2, ensure_ascii=False),
        "```",
        "",
        "## Runs",
        "",
        "| Run | Units | Failed | Detections | FPS | P95 ms | Signals |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for analysis in analyses:
        summary = analysis.summary
        lines.append(
            "| {run} | {units} | {failed} | {det} | {fps} | {p95} | {signals} |".format(
                run=analysis.run_id,
                units=summary.get("units_processed", "N/A"),
                failed=summary.get("units_failed", "N/A"),
                det=summary.get("total_detections", "N/A"),
                fps=summary.get("fps_effective", "N/A"),
                p95=summary.get("p95_latency_ms", "N/A"),
                signals=len(analysis.signals),
            )
        )
    lines.extend(["", "## Findings", ""])
    findings = sorted(
        [signal for analysis in analyses for signal in analysis.signals],
        key=lambda signal: (_severity_rank(signal.severity), signal.code),
    )
    if not findings:
        lines.append("No findings.")
    for signal in findings:
        lines.append(f"- **{signal.severity.upper()} {signal.code}**: {signal.message}")
        lines.append(f"  Suggestion: {signal.suggestion}")
    lines.append("")
    return "\n".join(lines)


def write_session_report(
    *,
    session_dir: Path,
    session_config: dict[str, Any],
    analyses: list[RunAnalysis],
    runs: list[dict[str, Any]],
) -> SessionReportResult:
    session_dir.mkdir(parents=True, exist_ok=True)
    json_path = session_dir / "session_report.json"
    markdown_path = session_dir / "session_report.md"
    payload = {
        "session_config": session_config,
        "runs": runs,
        "analyses": [analysis.model_dump(mode="json") for analysis in analyses],
    }
    json_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    markdown_path.write_text(_markdown(session_config, analyses), encoding="utf-8")
    return SessionReportResult(json_path=json_path, markdown_path=markdown_path)
```

- [x] **Step 4: Verify green**

Run: `source .venv/bin/activate && pytest tests/test_debug_session.py -v`

Expected: PASS.

- [x] **Step 5: Checkpoint**

Run: `source .venv/bin/activate && ruff check src/eovrt_media/debugging tests/test_debug_session.py`

Expected: PASS. Do not commit.

## Task 4: Debug Options In Local Two-Node Bench

**Files:**
- Modify: `src/eovrt_media/runtime/two_node_local.py`
- Modify: `tests/test_two_node_local.py`

- [x] **Step 1: Add failing tests for debug/session options**

Append to `tests/test_two_node_local.py`:

```python
def test_build_run_config_enables_debug_output_path(tmp_path: Path) -> None:
    options = LocalTwoNodeOptions(
        source="bench-val",
        model_ref="mock",
        device="cpu",
        outputs_base_dir=tmp_path / "runs",
        debug=True,
    )

    raw = build_run_config(
        options,
        endpoint="tcp://127.0.0.1:5601",
        heartbeat_endpoint="tcp://127.0.0.1:5602",
    )

    assert raw["debug"] == {"enabled": True}


def test_run_two_node_local_writes_wrapper_debug_events(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from eovrt_media.runtime import two_node_local

    monkeypatch.setattr(two_node_local.subprocess, "Popen", lambda *args, **kwargs: FakeProcess(0))
    monkeypatch.setattr(two_node_local, "wait_for_tcp_endpoint", lambda endpoint, timeout_s: True)
    monkeypatch.setattr(two_node_local, "latest_run_dir", lambda base_dir=Path("runs"): None)

    result = two_node_local.run_two_node_local(
        LocalTwoNodeOptions(
            source="bench-val",
            model_ref="mock",
            device="cpu",
            generated_dir=tmp_path / "generated",
            logs_dir=tmp_path / "logs",
            session_dir=tmp_path / "debug-session",
            debug=True,
        )
    )

    events_path = result.logs_dir / "debug_events.jsonl"
    assert events_path.exists()
    assert "process.start" in events_path.read_text(encoding="utf-8")
```

- [x] **Step 2: Verify red**

Run: `source .venv/bin/activate && pytest tests/test_two_node_local.py::test_build_run_config_enables_debug_output_path tests/test_two_node_local.py::test_run_two_node_local_writes_wrapper_debug_events -v`

Expected: FAIL because `LocalTwoNodeOptions` has no `debug` or `session_dir`.

- [x] **Step 3: Extend local bench options and wrapper events**

Modify `LocalTwoNodeOptions` in `src/eovrt_media/runtime/two_node_local.py`:

```python
    session_dir: Path | None = None
    debug: bool = False
```

Inside `build_run_config`, after `outputs`:

```python
    if options.debug:
        raw["debug"] = {"enabled": True}
```

Inside `run_two_node_local`, after `logs_dir` is computed:

```python
    if options.session_dir is not None:
        logs_dir = options.session_dir / "logs" / f"{options.source}_{options.codec}"
```

Before launching processes:

```python
    from eovrt_media.debugging.events import DebugEventWriter

    debug_writer = DebugEventWriter(logs_dir / "debug_events.jsonl", enabled=options.debug)
```

Write events around process lifecycle:

```python
    debug_writer.write(
        run_id=None,
        node="session",
        stage="process",
        event="process.start",
        codec=options.codec,
        extra={"node": "A", "config": str(config_path), "log": str(node_a_log)},
    )
```

Use the same shape for Node B and process exits, and call `debug_writer.close()` in the final cleanup.

- [x] **Step 4: Verify green**

Run: `source .venv/bin/activate && pytest tests/test_two_node_local.py -v`

Expected: PASS.

- [x] **Step 5: Checkpoint**

Run: `source .venv/bin/activate && ruff check src/eovrt_media/runtime/two_node_local.py tests/test_two_node_local.py`

Expected: PASS. Do not commit.

## Task 5: Debug Session Runner

**Files:**
- Create: `src/eovrt_media/debugging/session.py`
- Modify: `src/eovrt_media/debugging/__init__.py`
- Test: `tests/test_debug_session.py`

- [x] **Step 1: Add failing session runner tests**

Append to `tests/test_debug_session.py`:

```python
from eovrt_media.debugging.session import DebugRunOptions, run_debug_session


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
```

- [x] **Step 2: Verify red**

Run: `source .venv/bin/activate && pytest tests/test_debug_session.py::test_run_debug_session_executes_one_run_per_codec -v`

Expected: FAIL with missing `session`.

- [x] **Step 3: Implement session runner**

Create `src/eovrt_media/debugging/session.py`:

```python
"""Debug campaign runner built on top of the native local two-node bench."""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from eovrt_media.debugging.analyzer import RunAnalysis, analyze_run
from eovrt_media.debugging.reporter import write_session_report
from eovrt_media.runtime.two_node_local import LocalTwoNodeOptions, run_two_node_local


@dataclass(frozen=True)
class DebugRunOptions:
    source: str
    model_ref: str = "yoloe/yoloe-26s"
    device: str = "cuda:0"
    codecs: list[str] = field(default_factory=lambda: ["raw", "jpeg"])
    payload_format: str = "uint8_rgb"
    max_units: int | None = None
    video: Path | None = None
    rtsp_url: str | None = None
    session_id: str | None = None
    session_dir: Path | None = None
    debug: bool = True
    skip_probe: bool = False


@dataclass(frozen=True)
class DebugSessionResult:
    session_dir: Path
    runs: list[dict[str, Any]]
    analyses: list[RunAnalysis]
    report_json: Path
    report_markdown: Path


def _default_session_dir(options: DebugRunOptions) -> Path:
    session_id = options.session_id or f"{options.source}-{options.model_ref.replace('/', '-')}"
    return Path("runs/debug-sessions") / session_id


def _copy_if_exists(src: Path, dst: Path) -> None:
    if src.exists():
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(src, dst)


def run_debug_session(options: DebugRunOptions) -> DebugSessionResult:
    session_dir = options.session_dir or _default_session_dir(options)
    session_dir.mkdir(parents=True, exist_ok=True)
    generated_dir = session_dir / "generated-configs"
    session_config = {
        "source": options.source,
        "model_ref": options.model_ref,
        "device": options.device,
        "codecs": options.codecs,
        "payload_format": options.payload_format,
        "max_units": options.max_units,
        "debug": options.debug,
    }
    (session_dir / "session_config.yaml").write_text(
        yaml.safe_dump(session_config, sort_keys=False),
        encoding="utf-8",
    )

    runs: list[dict[str, Any]] = []
    analyses: list[RunAnalysis] = []
    for codec in options.codecs:
        local_result = run_two_node_local(
            LocalTwoNodeOptions(
                source=options.source,
                video=options.video,
                rtsp_url=options.rtsp_url,
                codec=codec,
                payload_format=options.payload_format,
                max_units=options.max_units,
                device=options.device,
                model_ref=options.model_ref,
                generated_dir=generated_dir,
                session_dir=session_dir,
                debug=options.debug,
                skip_probe=options.skip_probe,
            )
        )
        config_copy = generated_dir / f"{options.source}_{codec}.yaml"
        _copy_if_exists(local_result.config_path, config_copy)
        run_record = {
            "codec": codec,
            "ok": local_result.ok,
            "run_dir": str(local_result.run_dir) if local_result.run_dir else None,
            "run_id": local_result.summary.get("run_id") if local_result.summary else None,
            "node_a_log": str(local_result.node_a_log),
            "node_b_log": str(local_result.node_b_log),
            "config": str(config_copy),
            "failure_reason": local_result.failure_reason,
        }
        runs.append(run_record)
        if local_result.run_dir:
            analyses.append(
                analyze_run(
                    run_dir=local_result.run_dir,
                    node_logs=[local_result.node_a_log, local_result.node_b_log],
                    debug_expected=options.debug,
                )
            )

    report = write_session_report(
        session_dir=session_dir,
        session_config=session_config,
        analyses=analyses,
        runs=runs,
    )
    return DebugSessionResult(
        session_dir=session_dir,
        runs=runs,
        analyses=analyses,
        report_json=report.json_path,
        report_markdown=report.markdown_path,
    )
```

Update `src/eovrt_media/debugging/__init__.py`:

```python
from eovrt_media.debugging.session import DebugRunOptions, DebugSessionResult, run_debug_session

__all__ = [
    "DebugEvent",
    "DebugEventWriter",
    "DebugRunOptions",
    "DebugSessionResult",
    "run_debug_session",
]
```

- [x] **Step 4: Verify green**

Run: `source .venv/bin/activate && pytest tests/test_debug_session.py -v`

Expected: PASS.

- [x] **Step 5: Checkpoint**

Run: `source .venv/bin/activate && ruff check src/eovrt_media/debugging tests/test_debug_session.py`

Expected: PASS. Do not commit.

## Task 6: CLI `debug-run`

**Files:**
- Modify: `src/eovrt_media/cli.py`
- Test: `tests/test_cli_debug_run.py`

- [x] **Step 1: Write failing CLI tests**

Create `tests/test_cli_debug_run.py`:

```python
from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from eovrt_media.cli import app


runner = CliRunner()


def test_debug_run_wires_cli_options(monkeypatch) -> None:
    captured = {}

    class Result:
        session_dir = Path("runs/debug-sessions/session_x")
        report_json = session_dir / "session_report.json"
        report_markdown = session_dir / "session_report.md"
        runs = [{"codec": "raw"}, {"codec": "jpeg"}]
        analyses = []

    def fake_run_debug_session(options):
        captured["options"] = options
        return Result()

    monkeypatch.setattr("eovrt_media.debugging.session.run_debug_session", fake_run_debug_session)

    result = runner.invoke(
        app,
        [
            "debug-run",
            "--source",
            "bench-val",
            "--model-ref",
            "mock",
            "--device",
            "cpu",
            "--codecs",
            "raw,jpeg",
            "--max-units",
            "2",
        ],
    )

    assert result.exit_code == 0
    assert captured["options"].source == "bench-val"
    assert captured["options"].codecs == ["raw", "jpeg"]
    assert captured["options"].max_units == 2
    assert "session_report.md" in result.output
```

- [x] **Step 2: Verify red**

Run: `source .venv/bin/activate && pytest tests/test_cli_debug_run.py -v`

Expected: FAIL because `debug-run` command is not registered.

- [x] **Step 3: Implement CLI command**

Add to `src/eovrt_media/cli.py` before `validate-config`:

```python
@app.command(name="debug-run")
def debug_run(
    source: str = typer.Option(..., "--source"),
    video: Path | None = typer.Option(None, "--video"),
    rtsp_url: str | None = typer.Option(None, "--rtsp-url"),
    model_ref: str = typer.Option("yoloe/yoloe-26s", "--model-ref"),
    device: str = typer.Option("cuda:0", "--device"),
    codecs: str = typer.Option("raw,jpeg", "--codecs"),
    payload_format: str = typer.Option("uint8_rgb", "--payload-format"),
    max_units: int | None = typer.Option(None, "--max-units"),
    session_id: str | None = typer.Option(None, "--session-id"),
    debug: bool = typer.Option(True, "--debug/--no-debug"),
    skip_probe: bool = typer.Option(False, "--skip-probe"),
) -> None:
    """Ejecutar campaña de debug del media plane."""
    from eovrt_media.debugging.session import DebugRunOptions, run_debug_session

    codec_list = [item.strip() for item in codecs.split(",") if item.strip()]
    result = run_debug_session(
        DebugRunOptions(
            source=source,
            video=video,
            rtsp_url=rtsp_url,
            model_ref=model_ref,
            device=device,
            codecs=codec_list,
            payload_format=payload_format,
            max_units=max_units,
            session_id=session_id,
            debug=debug,
            skip_probe=skip_probe,
        )
    )
    console.print("\n[bold cyan]Debug session[/bold cyan]")
    console.print(f"  Session: {result.session_dir}")
    console.print(f"  Report JSON: {result.report_json}")
    console.print(f"  Report MD:   {result.report_markdown}")
    console.print(f"  Runs:        {len(result.runs)}")
```

- [x] **Step 4: Verify green**

Run: `source .venv/bin/activate && pytest tests/test_cli_debug_run.py -v`

Expected: PASS.

- [x] **Step 5: Checkpoint**

Run: `source .venv/bin/activate && ruff check src/eovrt_media/cli.py tests/test_cli_debug_run.py`

Expected: PASS. Do not commit.

## Task 7: Run-Level Debug Event File

**Files:**
- Modify: `src/eovrt_media/config/schemas.py`
- Modify: `src/eovrt_media/sinks/run_artifact_writer.py`
- Test: `tests/test_debug_events.py`

- [x] **Step 1: Add failing test for per-run debug file**

Append to `tests/test_debug_events.py`:

```python
from eovrt_media.config.schemas import RunConfig
from eovrt_media.runtime.run_context import RunContext
from eovrt_media.sinks import RunArtifactWriter


def test_run_artifact_writer_creates_debug_events_when_enabled(tmp_path: Path) -> None:
    cfg = RunConfig(
        run={"scenario": "EBE"},
        source={"type": "image_folder", "path": str(tmp_path)},
        model={"adapter": "mock", "device": "cpu"},
        prompts={"file": str(tmp_path / "prompts.yaml")},
        outputs={"run_dir": str(tmp_path / "runs"), "base_dir": str(tmp_path / "runs")},
        debug={"enabled": True},
    )
    (tmp_path / "prompts.yaml").write_text("version: v1\nitems:\n- id: person\n  text: person\n")
    context = RunContext(cfg)
    writer = RunArtifactWriter(context)

    writer.write_debug_event(node="B", stage="model", event="load_start")
    writer.close()

    assert (context.run_dir / "debug_events.jsonl").exists()
```

- [x] **Step 2: Verify red**

Run: `source .venv/bin/activate && pytest tests/test_debug_events.py::test_run_artifact_writer_creates_debug_events_when_enabled -v`

Expected: FAIL because `DebugConfig` or `debug` field does not exist.

- [x] **Step 3: Add debug config and writer integration**

In `src/eovrt_media/config/schemas.py`, add:

```python
class DebugConfig(BaseModel):
    """Debug instrumentation settings."""

    enabled: bool = False
```

Add to `RunConfig`:

```python
    debug: DebugConfig = Field(default_factory=DebugConfig)
```

In `src/eovrt_media/sinks/run_artifact_writer.py`, import `DebugEventWriter` near the existing sink imports:

```python
from eovrt_media.debugging.events import DebugEventWriter
```

Initialize `self.debug_sink` in `RunArtifactWriter.__init__` after `self.errors_sink = None`:

```python
        self.debug_sink = DebugEventWriter(
            self.run_dir / "debug_events.jsonl",
            enabled=self.context.config.debug.enabled,
        )
```

Add method:

```python
    def write_debug_event(self, **kwargs: Any) -> None:
        kwargs.setdefault("run_id", self.context.run_id)
        self.debug_sink.write(**kwargs)
```

Close it in `close()`:

```python
        self.debug_sink.close()
```

- [x] **Step 4: Verify green**

Run: `source .venv/bin/activate && pytest tests/test_debug_events.py -v`

Expected: PASS.

- [x] **Step 5: Checkpoint**

Run: `source .venv/bin/activate && ruff check src/eovrt_media/config/schemas.py src/eovrt_media/sinks/run_artifact_writer.py tests/test_debug_events.py`

Expected: PASS. Do not commit.

## Task 8: Minimal Runtime Instrumentation

**Files:**
- Modify: `src/eovrt_media/runtime/two_node.py`
- Test: `tests/test_cli_two_node.py`

- [x] **Step 1: Add focused tests for key debug events**

Add to `tests/test_cli_two_node.py`:

```python
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
        def write_effective_config(self): pass
        def write_debug_event(self, **kwargs):
            events.append(kwargs["event"])
        def close(self): pass
        def write_summary(self, tracker): pass
        def write_provenance(self): pass
        def write_manifest(self): pass

    class FakeTransport:
        def shutdown(self): pass

    class FakeAdapter:
        def load(self): pass
        def close(self): pass

    monkeypatch.setattr("eovrt_media.runtime.two_node.RunArtifactWriter", FakeWriter)
    monkeypatch.setattr("eovrt_media.runtime.two_node.create_transport", lambda **kwargs: FakeTransport())
    monkeypatch.setattr("eovrt_media.runtime.two_node.create_adapter", lambda model: FakeAdapter())
    monkeypatch.setattr("eovrt_media.runtime.two_node.run_consumer_loop", lambda *args, **kwargs: None)
    monkeypatch.setattr("eovrt_media.runtime.two_node.get_gpu_memory_peak_mb", lambda: 0.0)

    run_node_b(cfg)

    assert "model.load_start" in events
    assert "model.load_end" in events
```

- [x] **Step 2: Verify red**

Run: `source .venv/bin/activate && pytest tests/test_cli_two_node.py::test_node_b_writes_model_load_debug_events -v`

Expected: FAIL because debug events are not written.

- [x] **Step 3: Instrument conservative runtime events**

In `run_node_b`, after `artifact_writer.write_effective_config()` write:

```python
    artifact_writer.write_debug_event(node="B", stage="run", event="node.start")
```

After the existing multiline `transport = create_transport(` block closes, write:

```python
    artifact_writer.write_debug_event(node="B", stage="transport", event="transport.start")
```

Inside the existing `try:` block, wrap `adapter.load()` with:

```python
        artifact_writer.write_debug_event(node="B", stage="model", event="model.load_start")
        adapter.load()
        artifact_writer.write_debug_event(node="B", stage="model", event="model.load_end")
```

For v1, do not add direct Nodo A run artifact events in this task. Nodo A does not own the canonical run directory, so its lifecycle is covered by the local bench wrapper events and `node-a.log`. Keep this boundary until run/session correlation is stable.

- [x] **Step 4: Verify green**

Run: `source .venv/bin/activate && pytest tests/test_cli_two_node.py::test_node_b_writes_model_load_debug_events -v`

Expected: PASS.

- [x] **Step 5: Checkpoint**

Run: `source .venv/bin/activate && pytest tests/test_cli_two_node.py tests/test_debug_events.py -q`

Expected: PASS. Do not commit.

## Task 9: Integration And Manual Validation

**Files:**
- Modify: `docs/usage.md`
- Test: all debug tests and full suite.

- [x] **Step 1: Document debug-run**

Add to `docs/usage.md` after the native two-node bench section:

````markdown
### Framework de debug

Para ejecutar campañas diagnósticas y comparar corridas:

```bash
eovrt-media debug-run \
  --source bench-val \
  --model-ref yoloe/yoloe-26s \
  --device cuda:0 \
  --codecs raw,jpeg \
  --max-units 5 \
  --debug
```

Cada corrida puede escribir `debug_events.jsonl`; la campaña queda en
`runs/debug-sessions/` con `session_report.json` y `session_report.md`.
````

- [x] **Step 2: Run focused verification**

Run:

```bash
source .venv/bin/activate && pytest \
  tests/test_debug_events.py \
  tests/test_debug_analyzer.py \
  tests/test_debug_session.py \
  tests/test_cli_debug_run.py \
  tests/test_two_node_local.py \
  tests/test_cli_two_node.py -q
```

Expected: PASS.

- [x] **Step 3: Run full verification**

Run:

```bash
source .venv/bin/activate && pytest -q
source .venv/bin/activate && ruff check src tests
git diff --check
```

Expected: all pass.

- [x] **Step 4: Run manual mock debug session**

Run:

```bash
source .venv/bin/activate && eovrt-media debug-run \
  --source demo \
  --model-ref mock \
  --device cpu \
  --codecs raw,jpeg \
  --max-units 2 \
  --debug
```

Expected:

- command exits 0;
- creates `runs/debug-sessions/demo-mock/session_report.json` when `--session-id demo-mock` is supplied, or the generated equivalent when no session id is supplied;
- creates `runs/debug-sessions/demo-mock/session_report.md` when `--session-id demo-mock` is supplied, or the generated equivalent when no session id is supplied;
- two run records appear in the JSON report;
- runs have `debug_events.jsonl` when debug is enabled.

- [x] **Step 5: Run manual YOLOE debug session if GPU is available**

Run:

```bash
source .venv/bin/activate && eovrt-media debug-run \
  --source bench-val \
  --model-ref yoloe/yoloe-26s \
  --device cuda:0 \
  --codecs raw,jpeg \
  --max-units 5 \
  --debug
```

Expected:

- RAW and JPEG runs complete;
- session report compares both runs;
- no `RUN_SUMMARY_MISSING`;
- no `ERRORS_JSONL_NONEMPTY`;
- latency and VRAM signals are reported if thresholds are exceeded.

## Self-Review Notes

- Spec coverage: event contract, per-run debug events, session directory, analyzer, reporter, CLI, wrapper events, and validation are covered.
- Deliberate v1 limitation: deep Nodo A and transport serialization byte-level events are partially deferred until the wrapper/session/analyzer loop is stable. The plan still leaves the contract ready for them.
- User preference: no commits. Every task uses checkpoints and explicit verification instead of commit steps.

## Execution Closure

- Implemented inline on `main` with no commits.
- Focused verification: `34 passed` before the final audit.
- Final verification: `source .venv/bin/activate && make test` reported `253 passed`; `source .venv/bin/activate && make lint` passed; `git diff --check` passed.
- Mock debug session: `runs/debug-sessions/codex-smoke-debug-v2/` produced RAW/JPEG reports and per-run debug events.
- YOLOE CUDA debug session: `runs/debug-sessions/codex-yoloe-debug/` completed RAW/JPEG on `bench-val`; RAW reported high p95/p99 latency signals, JPEG completed without analyzer signals.
- Final audit fixes: debug event files now truncate stale content, default debug sessions use unique directories, failed local runs without `run_dir` are represented in reports, failed Nodo B runs no longer fall back to stale latest run dirs, and CLI/API reject empty codec lists.
