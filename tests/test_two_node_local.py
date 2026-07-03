from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from eovrt_media.runtime.two_node_local import (
    LocalTwoNodeOptions,
    LocalTwoNodeResult,
    build_run_config,
    collect_run_summary,
    resolve_run_dir_from_node_log,
    resolve_source,
    scan_log_warnings,
    wait_for_tcp_endpoint,
    write_generated_config,
)


def test_bench_val_source_resolves_catalog_ref() -> None:
    options = LocalTwoNodeOptions(source="bench-val", max_units=7)

    source = resolve_source(options)

    assert source == {"ref": "bench_v2_val"}


def test_video_source_requires_video_path() -> None:
    options = LocalTwoNodeOptions(source="video")

    with pytest.raises(ValueError, match="--video"):
        resolve_source(options)


def test_video_source_uses_inline_video_file(tmp_path: Path) -> None:
    video = tmp_path / "sample.mp4"
    video.write_bytes(b"not-a-real-video")
    options = LocalTwoNodeOptions(source="video", video=video)

    source = resolve_source(options)

    assert source == {"type": "video_file", "path": str(video)}


def test_ezviz_source_uses_rtsp_url_from_option() -> None:
    options = LocalTwoNodeOptions(source="ezviz", rtsp_url="rtsp://user:secret@cam/live")

    source = resolve_source(options)

    assert source["type"] == "rtsp"
    assert source["path"] == "rtsp://user:secret@cam/live"
    assert source["url"] == "rtsp://user:secret@cam/live"
    assert source["reconnect_retries"] == 5
    assert source["reconnect_delay_ms"] == 1000


def test_ezviz_source_requires_url() -> None:
    options = LocalTwoNodeOptions(source="ezviz")

    with pytest.raises(ValueError, match="EZVIZ_RTSP_URL"):
        resolve_source(options)


def test_build_run_config_sets_two_node_network_defaults(tmp_path: Path) -> None:
    options = LocalTwoNodeOptions(
        source="bench-val",
        codec="raw",
        payload_format="uint8_rgb",
        max_units=3,
        device="cpu",
        model_ref="mock",
        prompts_ref="cr01_cr02_bench_v2",
        save_previews=False,
    )

    raw = build_run_config(
        options,
        endpoint="tcp://127.0.0.1:5601",
        heartbeat_endpoint="tcp://127.0.0.1:5602",
    )

    assert raw["run"]["scenario"] == "EBE"
    assert raw["run"]["max_units"] == 3
    assert raw["source"] == {"ref": "bench_v2_val"}
    assert raw["model"] == {"ref": "mock", "device": "cpu"}
    assert raw["prompts"]["active_ids"] == ["person", "helmet", "vest", "bare_head"]
    assert raw["prompts"]["file"].endswith(
        "e-ovrt_experimental-setup/prompts/cr01_cr02_bench_v2.yaml"
    )
    assert raw["topology"] == {"mode": "two_node"}
    assert raw["transport"]["backend"] == "network"
    assert raw["transport"]["endpoint"] == "tcp://127.0.0.1:5601"
    assert raw["transport"]["heartbeat_endpoint"] == "tcp://127.0.0.1:5602"
    assert raw["transport"]["compression"] == {"codec": "raw", "quality": 90}
    assert raw["outputs"]["save_previews"] is False


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


def test_write_generated_config_persists_yaml(tmp_path: Path) -> None:
    raw = {
        "run": {"scenario": "EBE", "name": "local_two_node_bench_val"},
        "source": {"ref": "bench_v2_val"},
        "model": {"ref": "mock", "device": "cpu"},
        "prompts": {"ref": "cr01_cr02_bench_v2", "active_ids": ["person"]},
        "topology": {"mode": "two_node"},
        "transport": {
            "backend": "network",
            "endpoint": "tcp://127.0.0.1:5601",
            "heartbeat_endpoint": "tcp://127.0.0.1:5602",
            "payload_format": "uint8_rgb",
            "compression": {"codec": "jpeg", "quality": 90},
        },
    }

    path = write_generated_config(raw, tmp_path, stem="bench_val")

    assert path == tmp_path / "bench_val.yaml"
    assert yaml.safe_load(path.read_text()) == raw


def test_scan_log_warnings_finds_warning_and_error_lines(tmp_path: Path) -> None:
    log_path = tmp_path / "node-a.log"
    log_path.write_text(
        "info line\nWARNING dropped frame\nerror recoverable failure\n",
        encoding="utf-8",
    )

    warnings = scan_log_warnings(log_path)

    assert warnings == ["WARNING dropped frame", "error recoverable failure"]


def test_collect_run_summary_reads_summary_and_errors(tmp_path: Path) -> None:
    run_dir = tmp_path / "runs" / "run_x"
    run_dir.mkdir(parents=True)
    (run_dir / "summary.json").write_text(
        json.dumps(
            {
                "run_id": "run_x",
                "units_processed": 4,
                "units_failed": 1,
                "units_dropped": 2,
                "total_detections": 8,
                "detections_by_label": {"person": 4},
                "avg_latency_ms": 12.5,
                "p95_latency_ms": 20.0,
                "p99_latency_ms": 25.0,
                "fps_effective": 30.0,
                "gpu_memory_peak_mb": 512.0,
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "errors.jsonl").write_text('{"stage": "preview"}\n', encoding="utf-8")

    summary = collect_run_summary(run_dir)

    assert summary["run_id"] == "run_x"
    assert summary["units_processed"] == 4
    assert summary["errors_count"] == 1
    assert summary["detections_by_label"] == {"person": 4}


def test_resolve_run_dir_from_node_log_prefers_completed_run_id(tmp_path: Path) -> None:
    outputs = tmp_path / "runs"
    expected = outputs / "run_expected"
    unrelated_latest = outputs / "run_unrelated_latest"
    expected.mkdir(parents=True)
    unrelated_latest.mkdir()
    log_path = tmp_path / "node-b.log"
    log_path.write_text(
        "\nE-OVRT Media Plane — Nodo B (consumer)\n"
        "✓ Corrida completada: run_expected\n",
        encoding="utf-8",
    )

    run_dir = resolve_run_dir_from_node_log(log_path, outputs)

    assert run_dir == expected


def test_local_two_node_result_success_requires_zero_exit_codes(tmp_path: Path) -> None:
    result = LocalTwoNodeResult(
        config_path=tmp_path / "run.yaml",
        logs_dir=tmp_path,
        node_a_log=tmp_path / "node-a.log",
        node_b_log=tmp_path / "node-b.log",
        run_dir=None,
        node_a_returncode=0,
        node_b_returncode=0,
        summary={},
        warnings=[],
    )

    assert result.ok is True


def test_local_two_node_result_reports_failed_node(tmp_path: Path) -> None:
    result = LocalTwoNodeResult(
        config_path=tmp_path / "run.yaml",
        logs_dir=tmp_path,
        node_a_log=tmp_path / "node-a.log",
        node_b_log=tmp_path / "node-b.log",
        run_dir=None,
        node_a_returncode=-15,
        node_b_returncode=1,
        summary={},
        warnings=[],
    )

    assert result.ok is False
    assert "Nodo B exited with code 1" in result.failure_reason


def test_wait_for_tcp_endpoint_returns_false_for_unused_endpoint() -> None:
    assert wait_for_tcp_endpoint("tcp://127.0.0.1:1", timeout_s=0.05) is False


def test_run_two_node_local_raises_since_cli_removed(
    tmp_path: Path,
) -> None:
    # Task 17 eliminó el CLI `eovrt_media.cli` que esta orquestación spawneaba.
    # run_two_node_local ahora falla de forma explícita e informativa (RuntimeError)
    # en vez de un ModuleNotFoundError opaco desde los subprocesos. Sus helpers de
    # config (build_run_config, etc.) siguen soportados y testeados aparte.
    from eovrt_media.runtime import two_node_local

    options = LocalTwoNodeOptions(
        source="bench-val",
        model_ref="mock",
        device="cpu",
        generated_dir=tmp_path / "generated",
        logs_dir=tmp_path / "logs",
    )
    with pytest.raises(RuntimeError, match="no está soportado"):
        two_node_local.run_two_node_local(options)


# NOTE (Task 17): a real end-to-end test used to live here
# (test_run_two_node_local_processes_inline_image_folder_with_mock), spawning actual
# `python -m eovrt_media.cli run-producer/run-consumer` subprocesses (the only test in
# this file that did not mock `subprocess.Popen`). `cli.py` and the `eovrt-media` entry
# point were removed in Task 17, so that subprocess target no longer exists and the test
# could never pass again as written. It was removed rather than rewritten because
# `runtime/two_node_local.py` itself is slated for removal per the original Task 17 plan
# (its Phase 2 replacement is docker-compose) — see task-17-report.md for why the module
# was kept in this pass (it still backs `eovrt_media.tools.debug_run`).
