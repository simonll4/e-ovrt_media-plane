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


def test_debug_run_rejects_empty_codecs() -> None:
    result = runner.invoke(
        app,
        [
            "debug-run",
            "--source",
            "bench-val",
            "--codecs",
            ",",
        ],
    )

    assert result.exit_code == 1
    assert "al menos un codec" in result.output


def test_debug_run_reports_runner_errors_without_traceback(monkeypatch) -> None:
    def fake_run_debug_session(options):
        raise RuntimeError("boom")

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
            "raw",
            "--max-units",
            "2",
        ],
    )

    assert result.exit_code == 1
    assert "Debug session falló" in result.output
    assert "Traceback" not in result.output
