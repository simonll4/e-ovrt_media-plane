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
