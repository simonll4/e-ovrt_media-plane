"""Debug campaign runner built on top of the native local two-node bench."""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

import yaml

from eovrt_media.debugging.analyzer import RunAnalysis, Signal, analyze_run
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
    if options.session_id:
        session_id = options.session_id
    else:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
        model = options.model_ref.replace("/", "-")
        session_id = f"{options.source}_{model}_{timestamp}_{uuid4().hex[:8]}"
    return Path("runs/debug-sessions") / session_id


def _copy_if_exists(src: Path, dst: Path) -> None:
    if src.exists():
        if dst.exists() and src.resolve() == dst.resolve():
            return
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(src, dst)


def _failed_run_analysis(run_record: dict[str, Any], warnings: list[str]) -> RunAnalysis:
    codec = str(run_record["codec"])
    run_id = str(run_record.get("run_id") or f"failed_{codec}")
    failure_reason = str(run_record.get("failure_reason") or "Local debug run failed.")
    return RunAnalysis(
        run_id=run_id,
        run_dir=str(run_record.get("run_dir") or ""),
        summary={
            "run_id": run_id,
            "codec": codec,
            "ok": False,
            "failure_reason": failure_reason,
        },
        signals=[
            Signal(
                severity="error",
                code="LOCAL_RUN_FAILED",
                message=failure_reason,
                evidence={
                    "codec": codec,
                    "node_a_returncode": run_record.get("node_a_returncode"),
                    "node_b_returncode": run_record.get("node_b_returncode"),
                    "node_a_log": run_record.get("node_a_log"),
                    "node_b_log": run_record.get("node_b_log"),
                    "warnings": warnings[:20],
                },
                suggestion="Inspect node logs and generated config before trusting this session.",
            )
        ],
    )


def run_debug_session(options: DebugRunOptions) -> DebugSessionResult:
    if not options.codecs:
        raise ValueError("Debe indicar al menos un codec.")
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
        config_copy = generated_dir / local_result.config_path.name
        _copy_if_exists(local_result.config_path, config_copy)
        run_id = local_result.summary.get("run_id") if local_result.summary else f"failed_{codec}"
        run_record = {
            "codec": codec,
            "ok": local_result.ok,
            "run_dir": str(local_result.run_dir) if local_result.run_dir else None,
            "run_id": run_id,
            "node_a_log": str(local_result.node_a_log),
            "node_b_log": str(local_result.node_b_log),
            "node_a_returncode": local_result.node_a_returncode,
            "node_b_returncode": local_result.node_b_returncode,
            "config": str(config_copy),
            "failure_reason": local_result.failure_reason,
        }
        runs.append(run_record)
        if local_result.run_dir:
            analysis = analyze_run(
                run_dir=local_result.run_dir,
                node_logs=[local_result.node_a_log, local_result.node_b_log],
                debug_expected=options.debug,
            )
            if not local_result.ok:
                analysis.signals.append(
                    _failed_run_analysis(run_record, local_result.warnings).signals[0]
                )
            analyses.append(analysis)
        else:
            analyses.append(_failed_run_analysis(run_record, local_result.warnings))

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
