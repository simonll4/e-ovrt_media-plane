from __future__ import annotations

from pathlib import Path

import pytest

from eovrt_media.tools.debug_run import debug_run


def test_debug_run_wires_cli_options(monkeypatch, capsys: pytest.CaptureFixture[str]) -> None:
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

    debug_run(
        source="bench-val",
        model_ref="mock",
        device="cpu",
        codecs="raw,jpeg",
        max_units=2,
    )

    output = capsys.readouterr().out
    assert captured["options"].source == "bench-val"
    assert captured["options"].codecs == ["raw", "jpeg"]
    assert captured["options"].max_units == 2
    assert "session_report.md" in output


def test_debug_run_rejects_empty_codecs(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as excinfo:
        debug_run(source="bench-val", codecs=",")

    assert excinfo.value.code == 1
    assert "al menos un codec" in capsys.readouterr().out


def test_debug_run_reports_runner_errors_without_traceback(
    monkeypatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def fake_run_debug_session(options):
        raise RuntimeError("boom")

    monkeypatch.setattr("eovrt_media.debugging.session.run_debug_session", fake_run_debug_session)

    with pytest.raises(SystemExit) as excinfo:
        debug_run(
            source="bench-val",
            model_ref="mock",
            device="cpu",
            codecs="raw",
            max_units=2,
        )

    assert excinfo.value.code == 1
    output = capsys.readouterr().out
    assert "Debug session falló" in output
    assert "Traceback" not in output
