from __future__ import annotations

import json
from pathlib import Path

from eovrt_media.config.schemas import RunConfig
from eovrt_media.debugging.events import DebugEvent, DebugEventWriter
from eovrt_media.runtime.run_context import RunContext
from eovrt_media.sinks import RunArtifactWriter


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


def test_debug_event_writer_replaces_existing_file(tmp_path: Path) -> None:
    path = tmp_path / "debug_events.jsonl"
    path.write_text('{"event":"stale"}\n', encoding="utf-8")
    writer = DebugEventWriter(path, enabled=True)

    writer.write(run_id="run_x", node="B", stage="run", event="fresh")
    writer.close()

    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["event"] == "fresh"


def test_debug_event_writer_noop_when_disabled(tmp_path: Path) -> None:
    path = tmp_path / "debug_events.jsonl"
    writer = DebugEventWriter(path, enabled=False)

    writer.write(run_id="run_x", node="session", stage="process", event="start")
    writer.close()

    assert path.exists() is False


def test_run_artifact_writer_creates_debug_events_when_enabled(tmp_path: Path) -> None:
    cfg = RunConfig(
        run={"scenario": "EBE"},
        source={"type": "image_folder", "path": str(tmp_path)},
        model={"adapter": "mock", "device": "cpu"},
        prompts={"file": str(tmp_path / "prompts.yaml")},
        outputs={"run_dir": str(tmp_path / "runs"), "base_dir": str(tmp_path / "runs")},
        debug={"enabled": True},
    )
    (tmp_path / "prompts.yaml").write_text(
        "prompt_set:\n  id: v1\n  classes:\n"
        "    - id: person\n      phrasings: {default: [person]}\n"
    )
    context = RunContext(cfg)
    writer = RunArtifactWriter(context)

    writer.write_debug_event(node="B", stage="model", event="load_start")
    writer.close()

    assert (context.run_dir / "debug_events.jsonl").exists()
