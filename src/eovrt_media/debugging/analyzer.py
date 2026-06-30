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
                evidence={
                    "gpu_memory_peak_mb": gpu_peak,
                    "threshold_mb": gpu_memory_threshold_mb,
                },
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
