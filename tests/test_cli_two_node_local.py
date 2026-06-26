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
