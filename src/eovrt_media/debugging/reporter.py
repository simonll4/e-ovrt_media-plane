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
