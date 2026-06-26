# Banco Nativo Two-Node Local Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a preliminary native local two-node bench that launches the existing producer and consumer flows, makes source switching easy, and reports useful warnings/errors/performance signals.

**Architecture:** Add a focused `two_node_local` runtime helper that generates an auditable local run config, validates it with the existing loader, launches Nodo A and Nodo B as native subprocesses, captures separate logs, and summarizes the resulting run artifacts. The implementation must reuse `run-producer`, `run-consumer`, `load_run_config`, `NetworkTransportAdapter`, and existing source/model/prompt schemas instead of duplicating media-plane behavior.

**Tech Stack:** Python 3.11, Typer, PyYAML, Rich, pytest, ZeroMQ over loopback, existing `eovrt_media` runtime.

---

## File Structure

- Create `src/eovrt_media/runtime/two_node_local.py`: source-profile resolution, generated YAML writing, loopback endpoint allocation, subprocess orchestration, log scanning, summary extraction.
- Modify `src/eovrt_media/cli.py`: add `run-two-node-local` Typer command and map CLI flags into `LocalTwoNodeOptions`.
- Create `tests/test_two_node_local.py`: unit tests for source resolution/config generation and subprocess failure behavior.
- Create `tests/test_cli_two_node_local.py`: CLI smoke tests through Typer `CliRunner` for validation failures and option wiring.
- Modify `docs/usage.md`: document the preliminary native bench commands.

The first implementation should keep everything in one new runtime module. Split later only if the module becomes hard to reason about after real test runs.

### Task 1: Source Profiles And Config Generation

**Files:**
- Create: `src/eovrt_media/runtime/two_node_local.py`
- Test: `tests/test_two_node_local.py`

- [ ] **Step 1: Write failing tests for source resolution and generated YAML**

Create `tests/test_two_node_local.py` with:

```python
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from eovrt_media.runtime.two_node_local import (
    LocalTwoNodeOptions,
    build_run_config,
    resolve_source,
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
    assert raw["prompts"] == {
        "ref": "cr01_cr02_bench_v2",
        "active_ids": ["person", "helmet", "vest", "bare_head"],
    }
    assert raw["topology"] == {"mode": "two_node"}
    assert raw["transport"]["backend"] == "network"
    assert raw["transport"]["endpoint"] == "tcp://127.0.0.1:5601"
    assert raw["transport"]["heartbeat_endpoint"] == "tcp://127.0.0.1:5602"
    assert raw["transport"]["compression"] == {"codec": "raw", "quality": 90}
    assert raw["outputs"]["save_previews"] is False


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
```

- [ ] **Step 2: Run tests and verify they fail**

Run: `pytest tests/test_two_node_local.py -v`

Expected: FAIL during collection with `ModuleNotFoundError: No module named 'eovrt_media.runtime.two_node_local'`.

- [ ] **Step 3: Implement source resolution and config generation**

Create `src/eovrt_media/runtime/two_node_local.py` with:

```python
"""Native localhost bench for the existing two-node media-plane runtime."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os
import socket
from typing import Any

import yaml


DEFAULT_GENERATED_DIR = Path("configs/runs/local/generated")
DEFAULT_LOGS_DIR = Path("runs/local-two-node")
DEFAULT_ACTIVE_IDS = {
    "cr01_cr02_bench_v2": ["person", "helmet", "vest", "bare_head"],
    "cr01_cr02_v2_short": ["person", "helmet", "vest"],
}
SOURCE_REFS = {
    "bench-val": "bench_v2_val",
    "bench-test": "bench_v2_test",
    "demo": "demo_v2",
}
PROMPTS_BY_SOURCE = {
    "bench-val": "cr01_cr02_bench_v2",
    "bench-test": "cr01_cr02_bench_v2",
    "demo": "cr01_cr02_v2_short",
    "video": "cr01_cr02_v2_short",
    "ezviz": "cr01_cr02_v2_short",
}


@dataclass(frozen=True)
class LocalTwoNodeOptions:
    source: str
    video: Path | None = None
    rtsp_url: str | None = None
    codec: str = "jpeg"
    jpeg_quality: int = 90
    payload_format: str = "uint8_rgb"
    max_units: int | None = None
    device: str = "cuda:0"
    model_ref: str = "yoloe/yoloe-26s"
    prompts_ref: str | None = None
    save_previews: bool = False
    preview_max: int = 20
    generated_dir: Path = DEFAULT_GENERATED_DIR
    logs_dir: Path = DEFAULT_LOGS_DIR
    outputs_base_dir: Path = Path("runs")
    skip_probe: bool = False
    port_base: int | None = None
    startup_timeout_s: float = 10.0


def _require_supported_source(source: str) -> None:
    supported = {*SOURCE_REFS, "video", "ezviz"}
    if source not in supported:
        choices = ", ".join(sorted(supported))
        raise ValueError(f"--source debe ser uno de: {choices}")


def resolve_source(options: LocalTwoNodeOptions) -> dict[str, Any]:
    """Resolve a user-facing source profile into a run-config source section."""
    _require_supported_source(options.source)
    if options.source in SOURCE_REFS:
        return {"ref": SOURCE_REFS[options.source]}
    if options.source == "video":
        if options.video is None:
            raise ValueError("--source video requiere --video")
        return {"type": "video_file", "path": str(options.video)}
    rtsp_url = options.rtsp_url or os.environ.get("EZVIZ_RTSP_URL")
    if not rtsp_url:
        raise ValueError("--source ezviz requiere --rtsp-url o EZVIZ_RTSP_URL")
    return {
        "type": "rtsp",
        "path": rtsp_url,
        "url": rtsp_url,
        "reconnect_retries": 5,
        "reconnect_delay_ms": 1000,
    }


def resolve_prompts_ref(options: LocalTwoNodeOptions) -> str:
    """Return the prompt set reference for the selected source."""
    if options.prompts_ref:
        return options.prompts_ref
    _require_supported_source(options.source)
    return PROMPTS_BY_SOURCE[options.source]


def build_run_config(
    options: LocalTwoNodeOptions,
    *,
    endpoint: str,
    heartbeat_endpoint: str,
) -> dict[str, Any]:
    """Build the YAML-compatible run config used by both localhost nodes."""
    prompts_ref = resolve_prompts_ref(options)
    raw: dict[str, Any] = {
        "run": {
            "scenario": "EBE",
            "name": f"local_two_node_{options.source.replace('-', '_')}",
            "description": "Native localhost two-node bench generated by run-two-node-local.",
        },
        "source": resolve_source(options),
        "model": {"ref": options.model_ref, "device": options.device},
        "prompts": {
            "ref": prompts_ref,
            "active_ids": DEFAULT_ACTIVE_IDS.get(prompts_ref, ["person", "helmet", "vest"]),
        },
        "topology": {"mode": "two_node"},
        "transport": {
            "backend": "network",
            "endpoint": endpoint,
            "heartbeat_endpoint": heartbeat_endpoint,
            "payload_format": options.payload_format,
            "compression": {"codec": options.codec, "quality": options.jpeg_quality},
        },
        "outputs": {
            "run_dir": str(options.outputs_base_dir),
            "base_dir": str(options.outputs_base_dir),
            "save_previews": options.save_previews,
            "preview_max": options.preview_max,
        },
    }
    if options.max_units is not None:
        raw["run"]["max_units"] = options.max_units
    return raw


def write_generated_config(raw: dict[str, Any], generated_dir: Path, *, stem: str) -> Path:
    """Write a generated local run config and return its path."""
    generated_dir.mkdir(parents=True, exist_ok=True)
    path = generated_dir / f"{stem}.yaml"
    path.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
    return path


def unused_tcp_endpoint() -> str:
    """Return a loopback TCP endpoint string for ZeroMQ."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    return f"tcp://127.0.0.1:{port}"
```

- [ ] **Step 4: Run tests and verify they pass**

Run: `pytest tests/test_two_node_local.py -v`

Expected: PASS for all tests in `tests/test_two_node_local.py`.

- [ ] **Step 5: Commit**

```bash
git add src/eovrt_media/runtime/two_node_local.py tests/test_two_node_local.py
git commit -m "feat: generar config local two-node"
```

### Task 2: Subprocess Orchestration, Logs, And Summary Extraction

**Files:**
- Modify: `src/eovrt_media/runtime/two_node_local.py`
- Modify: `tests/test_two_node_local.py`

- [ ] **Step 1: Add failing tests for process orchestration helpers**

Append to `tests/test_two_node_local.py`:

```python
import json
import subprocess

from eovrt_media.runtime.two_node_local import (
    LocalTwoNodeResult,
    collect_run_summary,
    scan_log_warnings,
    wait_for_tcp_endpoint,
)


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
```

- [ ] **Step 2: Run tests and verify they fail**

Run: `pytest tests/test_two_node_local.py -v`

Expected: FAIL with import errors for `LocalTwoNodeResult`, `collect_run_summary`, `scan_log_warnings`, and `wait_for_tcp_endpoint`.

- [ ] **Step 3: Implement orchestration support helpers**

Append these definitions to `src/eovrt_media/runtime/two_node_local.py`:

```python
from dataclasses import field
import json
import subprocess
import sys
import time
from urllib.parse import urlparse


@dataclass(frozen=True)
class LocalTwoNodeResult:
    config_path: Path
    logs_dir: Path
    node_a_log: Path
    node_b_log: Path
    run_dir: Path | None
    node_a_returncode: int | None
    node_b_returncode: int | None
    summary: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.node_a_returncode == 0 and self.node_b_returncode == 0

    @property
    def failure_reason(self) -> str:
        if self.ok:
            return ""
        if self.node_b_returncode not in (0, None):
            return f"Nodo B exited with code {self.node_b_returncode}"
        if self.node_a_returncode not in (0, None):
            return f"Nodo A exited with code {self.node_a_returncode}"
        return "Two-node local run did not complete"


def _endpoint_host_port(endpoint: str) -> tuple[str, int]:
    parsed = urlparse(endpoint)
    if parsed.scheme != "tcp" or parsed.hostname is None or parsed.port is None:
        raise ValueError(f"Solo endpoints tcp://host:port son soportados: {endpoint}")
    return parsed.hostname, parsed.port


def wait_for_tcp_endpoint(endpoint: str, *, timeout_s: float) -> bool:
    """Wait until a TCP endpoint accepts connections."""
    host, port = _endpoint_host_port(endpoint)
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            with socket.create_connection((host, port), timeout=0.2):
                return True
        except OSError:
            time.sleep(0.05)
    return False


def scan_log_warnings(log_path: Path) -> list[str]:
    """Return warning/error lines from a node log."""
    if not log_path.exists():
        return []
    matches: list[str] = []
    for line in log_path.read_text(encoding="utf-8", errors="replace").splitlines():
        lowered = line.lower()
        if "warning" in lowered or "error" in lowered or "traceback" in lowered:
            matches.append(line)
    return matches


def collect_run_summary(run_dir: Path | None) -> dict[str, Any]:
    """Read summary.json and count errors.jsonl lines from a completed run."""
    if run_dir is None:
        return {}
    summary_path = run_dir / "summary.json"
    if not summary_path.exists():
        return {}
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    errors_path = run_dir / "errors.jsonl"
    summary["errors_count"] = (
        len(errors_path.read_text(encoding="utf-8").splitlines())
        if errors_path.exists()
        else 0
    )
    return summary


def _command_for_node(node: str, config_path: Path) -> list[str]:
    command = "run-producer" if node == "a" else "run-consumer"
    return [sys.executable, "-m", "eovrt_media.cli", command, "--config", str(config_path)]


def _subprocess_env() -> dict[str, str]:
    env = os.environ.copy()
    repo_src = Path(__file__).resolve().parents[2]
    existing = env.get("PYTHONPATH")
    env["PYTHONPATH"] = f"{repo_src}{os.pathsep}{existing}" if existing else str(repo_src)
    return env


def latest_run_dir(base_dir: Path = Path("runs")) -> Path | None:
    """Return the newest run directory containing summary.json."""
    if not base_dir.exists():
        return None
    candidates = [path for path in base_dir.iterdir() if (path / "summary.json").exists()]
    if not candidates:
        return None
    return max(candidates, key=lambda path: path.stat().st_mtime)
```

- [ ] **Step 4: Run tests and verify they pass**

Run: `pytest tests/test_two_node_local.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/eovrt_media/runtime/two_node_local.py tests/test_two_node_local.py
git commit -m "feat: agregar soporte de logs two-node local"
```

### Task 3: Native Local Runner

**Files:**
- Modify: `src/eovrt_media/runtime/two_node_local.py`
- Modify: `tests/test_two_node_local.py`

- [ ] **Step 1: Add a failing subprocess orchestration test**

Append to `tests/test_two_node_local.py`:

```python
class FakeProcess:
    def __init__(self, returncode: int = 0) -> None:
        self.returncode = returncode
        self.terminated = False

    def wait(self, timeout: float | None = None) -> int:
        return self.returncode

    def poll(self) -> int | None:
        return self.returncode

    def terminate(self) -> None:
        self.terminated = True
        self.returncode = -15


def test_run_two_node_local_generates_config_and_starts_nodes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from eovrt_media.runtime import two_node_local

    started: list[list[str]] = []

    def fake_popen(command, stdout, stderr, cwd, env):
        started.append(command)
        return FakeProcess(0)

    monkeypatch.setattr(two_node_local.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(two_node_local, "wait_for_tcp_endpoint", lambda endpoint, timeout_s: True)
    monkeypatch.setattr(two_node_local, "latest_run_dir", lambda base_dir=Path("runs"): None)

    options = LocalTwoNodeOptions(
        source="bench-val",
        model_ref="mock",
        device="cpu",
        generated_dir=tmp_path / "generated",
        logs_dir=tmp_path / "logs",
    )

    result = two_node_local.run_two_node_local(options)

    assert result.ok is True
    assert result.config_path.exists()
    assert result.node_a_log == result.logs_dir / "node-a.log"
    assert result.node_b_log == result.logs_dir / "node-b.log"
    assert started[0][-3:] == ["run-producer", "--config", str(result.config_path)]
    assert started[1][-3:] == ["run-consumer", "--config", str(result.config_path)]
```

- [ ] **Step 2: Run the test and verify it fails**

Run: `pytest tests/test_two_node_local.py::test_run_two_node_local_generates_config_and_starts_nodes -v`

Expected: FAIL with `AttributeError: module 'eovrt_media.runtime.two_node_local' has no attribute 'run_two_node_local'`.

- [ ] **Step 3: Implement `run_two_node_local`**

Append to `src/eovrt_media/runtime/two_node_local.py`:

```python
def _endpoints_for_options(options: LocalTwoNodeOptions) -> tuple[str, str]:
    if options.port_base is not None:
        return (
            f"tcp://127.0.0.1:{options.port_base}",
            f"tcp://127.0.0.1:{options.port_base + 1}",
        )
    return unused_tcp_endpoint(), unused_tcp_endpoint()


def _open_log(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    return path.open("w", encoding="utf-8")


def _terminate_process(process: subprocess.Popen[Any] | None) -> None:
    if process is None or process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=5.0)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5.0)


def run_two_node_local(options: LocalTwoNodeOptions) -> LocalTwoNodeResult:
    """Generate config, launch Nodo A and Nodo B, and collect local bench results."""
    endpoint, heartbeat_endpoint = _endpoints_for_options(options)
    raw_config = build_run_config(
        options,
        endpoint=endpoint,
        heartbeat_endpoint=heartbeat_endpoint,
    )
    config_path = write_generated_config(
        raw_config,
        options.generated_dir,
        stem=f"{options.source.replace('-', '_')}_{options.codec}",
    )

    from eovrt_media.config import load_run_config

    load_run_config(config_path)

    session_name = time.strftime("%Y%m%d-%H%M%S")
    logs_dir = options.logs_dir / session_name
    node_a_log = logs_dir / "node-a.log"
    node_b_log = logs_dir / "node-b.log"
    node_a: subprocess.Popen[Any] | None = None
    node_b: subprocess.Popen[Any] | None = None

    with _open_log(node_a_log) as node_a_stream, _open_log(node_b_log) as node_b_stream:
        try:
            node_a = subprocess.Popen(
                _command_for_node("a", config_path),
                stdout=node_a_stream,
                stderr=subprocess.STDOUT,
                cwd=Path.cwd(),
                env=_subprocess_env(),
            )
            if not wait_for_tcp_endpoint(endpoint, timeout_s=options.startup_timeout_s):
                _terminate_process(node_a)
                return LocalTwoNodeResult(
                    config_path=config_path,
                    logs_dir=logs_dir,
                    node_a_log=node_a_log,
                    node_b_log=node_b_log,
                    run_dir=None,
                    node_a_returncode=node_a.returncode,
                    node_b_returncode=None,
                    summary={},
                    warnings=scan_log_warnings(node_a_log),
                )

            node_b = subprocess.Popen(
                _command_for_node("b", config_path),
                stdout=node_b_stream,
                stderr=subprocess.STDOUT,
                cwd=Path.cwd(),
                env=_subprocess_env(),
            )
            node_b_returncode = node_b.wait()
            node_a_returncode = node_a.wait(timeout=options.startup_timeout_s)
        finally:
            _terminate_process(node_b)
            _terminate_process(node_a)

    run_dir = latest_run_dir(options.outputs_base_dir)
    warnings = [*scan_log_warnings(node_a_log), *scan_log_warnings(node_b_log)]
    return LocalTwoNodeResult(
        config_path=config_path,
        logs_dir=logs_dir,
        node_a_log=node_a_log,
        node_b_log=node_b_log,
        run_dir=run_dir,
        node_a_returncode=node_a.returncode if node_a is not None else None,
        node_b_returncode=node_b.returncode if node_b is not None else None,
        summary=collect_run_summary(run_dir),
        warnings=warnings,
    )
```

- [ ] **Step 4: Run focused tests**

Run: `pytest tests/test_two_node_local.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/eovrt_media/runtime/two_node_local.py tests/test_two_node_local.py
git commit -m "feat: orquestar banco nativo two-node"
```

### Task 4: CLI Command

**Files:**
- Modify: `src/eovrt_media/cli.py`
- Create: `tests/test_cli_two_node_local.py`

- [ ] **Step 1: Write failing CLI tests**

Create `tests/test_cli_two_node_local.py` with:

```python
from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from eovrt_media.cli import app


runner = CliRunner()


def test_run_two_node_local_rejects_video_without_path() -> None:
    result = runner.invoke(app, ["run-two-node-local", "--source", "video"])

    assert result.exit_code == 1
    assert "--source video requiere --video" in result.output


def test_run_two_node_local_wires_options(monkeypatch) -> None:
    captured = {}

    class Result:
        ok = True
        config_path = Path("configs/runs/local/generated/bench_val_jpeg.yaml")
        logs_dir = Path("runs/local-two-node/20260626-143000")
        run_dir = Path("runs/run_x")
        summary = {"run_id": "run_x", "units_processed": 4, "errors_count": 0}
        warnings = []
        failure_reason = ""

    def fake_run(options):
        captured["options"] = options
        return Result()

    monkeypatch.setattr("eovrt_media.runtime.two_node_local.run_two_node_local", fake_run)

    result = runner.invoke(
        app,
        [
            "run-two-node-local",
            "--source",
            "bench-val",
            "--codec",
            "raw",
            "--max-units",
            "4",
            "--device",
            "cpu",
            "--model-ref",
            "mock",
        ],
    )

    assert result.exit_code == 0
    assert captured["options"].source == "bench-val"
    assert captured["options"].codec == "raw"
    assert captured["options"].max_units == 4
    assert captured["options"].device == "cpu"
    assert captured["options"].model_ref == "mock"
    assert "run_x" in result.output
```

- [ ] **Step 2: Run tests and verify they fail**

Run: `pytest tests/test_cli_two_node_local.py -v`

Expected: FAIL because `run-two-node-local` is not registered.

- [ ] **Step 3: Add the Typer command**

In `src/eovrt_media/cli.py`, add this command before `validate-config`:

```python
@app.command(name="run-two-node-local")
def run_two_node_local_command(
    source: str = typer.Option(
        ...,
        "--source",
        help="Fuente: bench-val, bench-test, demo, video, ezviz.",
    ),
    video: Path | None = typer.Option(
        None,
        "--video",
        help="Archivo de video para --source video.",
    ),
    rtsp_url: str | None = typer.Option(
        None,
        "--rtsp-url",
        help="URL RTSP para --source ezviz.",
    ),
    codec: str = typer.Option("jpeg", "--codec", help="Compresión de red: jpeg o raw."),
    jpeg_quality: int = typer.Option(90, "--jpeg-quality", min=1, max=100),
    payload_format: str = typer.Option("uint8_rgb", "--payload-format"),
    max_units: int | None = typer.Option(None, "--max-units"),
    device: str = typer.Option("cuda:0", "--device"),
    model_ref: str = typer.Option("yoloe/yoloe-26s", "--model-ref"),
    prompts_ref: str | None = typer.Option(None, "--prompts-ref"),
    save_previews: bool = typer.Option(False, "--save-previews/--no-save-previews"),
    skip_probe: bool = typer.Option(False, "--skip-probe"),
    port_base: int | None = typer.Option(None, "--port-base"),
) -> None:
    """Ejecutar banco preliminar two-node nativo en localhost."""
    from eovrt_media.runtime.two_node_local import LocalTwoNodeOptions, run_two_node_local

    try:
        result = run_two_node_local(
            LocalTwoNodeOptions(
                source=source,
                video=video,
                rtsp_url=rtsp_url,
                codec=codec,
                jpeg_quality=jpeg_quality,
                payload_format=payload_format,
                max_units=max_units,
                device=device,
                model_ref=model_ref,
                prompts_ref=prompts_ref,
                save_previews=save_previews,
                skip_probe=skip_probe,
                port_base=port_base,
            )
        )
    except Exception as error:
        console.print(f"[red]✗ Banco two-node local falló:[/red] {error}")
        raise typer.Exit(1)

    console.print("\n[bold cyan]Banco two-node local[/bold cyan]")
    console.print(f"  Config:      {result.config_path}")
    console.print(f"  Logs:        {result.logs_dir}")
    if result.run_dir:
        console.print(f"  Run dir:     {result.run_dir}")
    if result.summary:
        console.print(f"  Run ID:      {result.summary.get('run_id', 'N/A')}")
        console.print(f"  Units:       {result.summary.get('units_processed', 'N/A')}")
        console.print(f"  Failures:    {result.summary.get('units_failed', 'N/A')}")
        console.print(f"  Errors:      {result.summary.get('errors_count', 0)}")
        console.print(f"  FPS:         {result.summary.get('fps_effective', 'N/A')}")
        console.print(f"  P95 ms:      {result.summary.get('p95_latency_ms', 'N/A')}")
    if result.warnings:
        console.print("\n[yellow]Warnings/errors detectados:[/yellow]")
        for line in result.warnings[:20]:
            console.print(f"  {line}")
    if not result.ok:
        console.print(f"[red]✗ {result.failure_reason}[/red]")
        raise typer.Exit(1)
    console.print("[green]✓ Banco two-node local completado.[/green]")
```

- [ ] **Step 4: Run CLI tests**

Run: `pytest tests/test_cli_two_node_local.py -v`

Expected: PASS.

- [ ] **Step 5: Run lint on touched Python files**

Run: `ruff check src/eovrt_media/cli.py src/eovrt_media/runtime/two_node_local.py tests/test_two_node_local.py tests/test_cli_two_node_local.py`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/eovrt_media/cli.py src/eovrt_media/runtime/two_node_local.py tests/test_two_node_local.py tests/test_cli_two_node_local.py
git commit -m "feat: exponer banco two-node local en CLI"
```

### Task 5: RTSP Probe Hook

**Files:**
- Modify: `src/eovrt_media/runtime/two_node_local.py`
- Modify: `tests/test_two_node_local.py`

- [ ] **Step 1: Add failing tests for RTSP probe behavior**

Append to `tests/test_two_node_local.py`:

```python
def test_probe_runs_for_ezviz_unless_skipped(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from eovrt_media.runtime import two_node_local

    probed = []

    monkeypatch.setattr(two_node_local.subprocess, "Popen", lambda *args, **kwargs: FakeProcess(0))
    monkeypatch.setattr(two_node_local, "wait_for_tcp_endpoint", lambda endpoint, timeout_s: True)
    monkeypatch.setattr(two_node_local, "latest_run_dir", lambda base_dir=Path("runs"): None)
    monkeypatch.setattr(two_node_local, "probe_rtsp_config", lambda config_path, frames=30: probed.append(config_path))

    options = LocalTwoNodeOptions(
        source="ezviz",
        rtsp_url="rtsp://user:secret@cam/live",
        model_ref="mock",
        device="cpu",
        generated_dir=tmp_path / "generated",
        logs_dir=tmp_path / "logs",
    )

    two_node_local.run_two_node_local(options)

    assert len(probed) == 1


def test_probe_is_skipped_when_requested(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from eovrt_media.runtime import two_node_local

    probed = []

    monkeypatch.setattr(two_node_local.subprocess, "Popen", lambda *args, **kwargs: FakeProcess(0))
    monkeypatch.setattr(two_node_local, "wait_for_tcp_endpoint", lambda endpoint, timeout_s: True)
    monkeypatch.setattr(two_node_local, "latest_run_dir", lambda base_dir=Path("runs"): None)
    monkeypatch.setattr(two_node_local, "probe_rtsp_config", lambda config_path, frames=30: probed.append(config_path))

    options = LocalTwoNodeOptions(
        source="ezviz",
        rtsp_url="rtsp://user:secret@cam/live",
        model_ref="mock",
        device="cpu",
        generated_dir=tmp_path / "generated",
        logs_dir=tmp_path / "logs",
        skip_probe=True,
    )

    two_node_local.run_two_node_local(options)

    assert probed == []
```

- [ ] **Step 2: Run tests and verify they fail**

Run: `pytest tests/test_two_node_local.py::test_probe_runs_for_ezviz_unless_skipped tests/test_two_node_local.py::test_probe_is_skipped_when_requested -v`

Expected: FAIL because `probe_rtsp_config` is not defined and `run_two_node_local` does not call it.

- [ ] **Step 3: Implement RTSP probe hook**

In `src/eovrt_media/runtime/two_node_local.py`, add:

```python
def probe_rtsp_config(config_path: Path, *, frames: int = 30) -> None:
    """Probe an RTSP run config using the existing credential-safe probe script."""
    from scripts.probe_rtsp import probe

    probe(config_path, frames=frames)
```

Then, inside `run_two_node_local`, immediately after `load_run_config(config_path)`:

```python
    if options.source == "ezviz" and not options.skip_probe:
        probe_rtsp_config(config_path, frames=30)
```

- [ ] **Step 4: Run focused tests**

Run: `pytest tests/test_two_node_local.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/eovrt_media/runtime/two_node_local.py tests/test_two_node_local.py
git commit -m "feat: sondar rtsp antes del banco local"
```

### Task 6: Integration Smoke Test With Mock Detector

**Files:**
- Modify: `tests/test_two_node_local.py`

- [ ] **Step 1: Add a real end-to-end smoke test**

Append to `tests/test_two_node_local.py`:

```python
import cv2
import numpy as np


def _write_images(folder: Path, count: int = 2) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    for index in range(count):
        image = np.full((48, 64, 3), index * 40, dtype=np.uint8)
        cv2.imwrite(str(folder / f"img_{index:03d}.jpg"), image)


def test_run_two_node_local_processes_inline_image_folder_with_mock(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    images = tmp_path / "images"
    _write_images(images, count=2)

    prompts_path = tmp_path / "prompts.yaml"
    prompts_path.write_text(
        "version: v1\nitems:\n  - id: person\n    text: person\n",
        encoding="utf-8",
    )

    from eovrt_media.runtime import two_node_local

    def fake_resolve_source(options):
        return {"type": "image_folder", "path": str(images)}

    def fake_resolve_prompts_ref(options):
        return "v1"

    monkeypatch.setattr(two_node_local, "resolve_source", fake_resolve_source)
    monkeypatch.setattr(two_node_local, "resolve_prompts_ref", fake_resolve_prompts_ref)
    monkeypatch.setitem(two_node_local.DEFAULT_ACTIVE_IDS, "v1", ["person"])

    original_build = two_node_local.build_run_config

    def build_with_prompt_file(options, endpoint, heartbeat_endpoint):
        raw = original_build(options, endpoint=endpoint, heartbeat_endpoint=heartbeat_endpoint)
        raw["model"] = {"adapter": "mock", "device": "cpu"}
        raw["prompts"] = {"file": str(prompts_path), "active_ids": ["person"]}
        return raw

    monkeypatch.setattr(two_node_local, "build_run_config", build_with_prompt_file)
    monkeypatch.chdir(Path.cwd())

    result = two_node_local.run_two_node_local(
        LocalTwoNodeOptions(
            source="bench-val",
            model_ref="mock",
            device="cpu",
            max_units=2,
            generated_dir=tmp_path / "generated",
            logs_dir=tmp_path / "logs",
            outputs_base_dir=tmp_path / "runs",
            startup_timeout_s=10.0,
        )
    )

    assert result.ok is True
    assert result.summary["units_processed"] == 2
    assert result.summary["errors_count"] == 0
```

- [ ] **Step 2: Run the integration smoke test**

Run: `pytest tests/test_two_node_local.py::test_run_two_node_local_processes_inline_image_folder_with_mock -v`

Expected: PASS. If it fails because the subprocess cannot import `eovrt_media`, inspect `node-a.log` and `node-b.log`, then fix `_subprocess_env()` so `PYTHONPATH` includes the repo `src` directory.

- [ ] **Step 3: Run all two-node local tests**

Run: `pytest tests/test_two_node_local.py tests/test_cli_two_node_local.py -v`

Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add tests/test_two_node_local.py
git commit -m "test: cubrir banco two-node local end-to-end"
```

### Task 7: Usage Documentation And Final Verification

**Files:**
- Modify: `docs/usage.md`

- [ ] **Step 1: Document the preliminary native bench**

In `docs/usage.md`, after the existing "Topología dos nodos" section, add:

````markdown
### Banco local nativo two-node

Para probar a fondo el plano de medios en una sola PC sin Docker, usar el banco
nativo. El comando genera una config local bajo `configs/runs/local/generated/`,
levanta Nodo A y Nodo B como procesos separados sobre loopback, guarda logs por
nodo y resume los artefactos de la corrida.

```bash
eovrt-media run-two-node-local --source bench-val --codec jpeg --max-units 200
eovrt-media run-two-node-local --source bench-val --codec raw --max-units 200
eovrt-media run-two-node-local --source video --video data/samples/videos/sample.mp4 --codec jpeg
EZVIZ_RTSP_URL='rtsp://user:password@camera/stream' \
  eovrt-media run-two-node-local --source ezviz --max-units 300
```

`configs/runs/local/` está ignorado por Git; no versionar URIs RTSP ni endpoints
locales. Para RTSP, el comando ejecuta una sonda corta antes de levantar nodos
salvo que se pase `--skip-probe`.
````

- [ ] **Step 2: Run full test and lint verification**

Run:

```bash
pytest -q
ruff check src tests
git diff --check
```

Expected: all commands pass.

- [ ] **Step 3: Run a preliminary CLI smoke command**

Run:

```bash
eovrt-media run-two-node-local --source demo --model-ref mock --device cpu --max-units 2 --codec raw
```

Expected: command exits 0, prints `Banco two-node local completado`, and writes node logs under `runs/local-two-node/`.

- [ ] **Step 4: Commit**

```bash
git add docs/usage.md
git commit -m "docs: documentar banco two-node local"
```

## Self-Review Notes

- Spec coverage: source switching, generated configs, native two-node subprocesses, logs, summaries, RTSP probe, validation, and documentation are covered by Tasks 1-7.
- Productive always-running service remains outside this plan by design; the plan only creates the preliminary bench needed to discover operational gaps.
- The plan intentionally reuses the existing producer/consumer CLI and does not alter `NetworkTransportAdapter`, source adapters, model adapters, or sink contracts.
