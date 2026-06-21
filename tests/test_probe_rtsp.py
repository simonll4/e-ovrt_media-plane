"""Tests for the credential-safe RTSP probe script."""
from __future__ import annotations

import logging
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

from eovrt_media.contracts import VisualUnit

sys.path.insert(0, str(Path(__file__).parents[1]))

from scripts import probe_rtsp


def test_redact_rtsp_url_hides_credentials_and_query() -> None:
    raw_url = "rtsp://camera_user:camera_password@192.168.1.82:554/Streaming/Channels/1?token=value"

    assert (
        probe_rtsp.redact_rtsp_url(raw_url)
        == "rtsp://192.168.1.82:554/Streaming/Channels/1"
    )


def test_redact_rtsp_url_fails_closed_for_an_opaque_url() -> None:
    redacted = probe_rtsp.redact_rtsp_url("rtsp:user:secret@camera:554/live?token=value")

    assert redacted == "rtsp://unknown-host/"
    assert "user" not in redacted
    assert "secret" not in redacted
    assert "token" not in redacted


@pytest.mark.parametrize(
    "raw_url",
    [
        "rtsp://user:secret@camera:badport/live?token=value",
        "rtsp://user:secret@[malformed/live?token=value",
    ],
)
def test_redact_rtsp_url_fails_closed_for_invalid_authority(raw_url: str) -> None:
    redacted = probe_rtsp.redact_rtsp_url(raw_url)

    assert redacted == "rtsp://unknown-host/"
    assert "user" not in redacted
    assert "secret" not in redacted
    assert "token" not in redacted


def test_probe_reads_requested_frames_with_sanitized_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    raw_url = "rtsp://camera_user:camera_password@example.test:8554/live?token=value"
    config = SimpleNamespace(
        source=SimpleNamespace(
            type="rtsp",
            url=raw_url,
            path="unused-fallback",
            reconnect_retries=7,
            reconnect_delay_ms=125,
        )
    )
    source_args: dict[str, object] = {}

    class FakeRtspSource:
        def __init__(self, **kwargs: object) -> None:
            source_args.update(kwargs)

        def __iter__(self):
            for frame_index in range(3):
                yield VisualUnit(
                    unit_id=f"frame_{frame_index}",
                    source_type="video_frame",
                    frame_index=frame_index,
                    width=1920,
                    height=1080,
                )

    monkeypatch.setattr(probe_rtsp, "load_run_config", lambda _path: config)
    monkeypatch.setattr(probe_rtsp, "RtspSource", FakeRtspSource)

    result = probe_rtsp.probe(Path("dummy-config.yaml"), frames=3)

    assert source_args == {
        "url": raw_url,
        "reconnect_retries": 7,
        "reconnect_delay_ms": 125,
        "max_units": 3,
    }
    assert result.endpoint == "rtsp://example.test:8554/live"
    assert result.frames_read == 3
    assert (result.width, result.height) == (1920, 1080)


def test_probe_accepts_whitespace_and_case_rtsp_source_type(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = SimpleNamespace(
        source=SimpleNamespace(
            type=" RTSP ",
            url="rtsp://example.test/live",
            path="unused-fallback",
            reconnect_retries=1,
            reconnect_delay_ms=0,
        )
    )

    class FakeRtspSource:
        def __init__(self, **_kwargs: object) -> None:
            pass

        def __iter__(self):
            yield VisualUnit(
                unit_id="frame_0",
                source_type="video_frame",
                frame_index=0,
                width=640,
                height=480,
            )

    monkeypatch.setattr(probe_rtsp, "load_run_config", lambda _path: config)
    monkeypatch.setattr(probe_rtsp, "RtspSource", FakeRtspSource)

    result = probe_rtsp.probe(Path("dummy-config.yaml"), frames=1)

    assert result.frames_read == 1


def test_probe_rejects_zero_frames() -> None:
    with pytest.raises(ValueError, match="frames"):
        probe_rtsp.probe(Path("dummy-config.yaml"), frames=0)


def test_build_parser_requires_config_and_defaults_frames_to_thirty() -> None:
    parser = probe_rtsp.build_parser()

    assert parser.parse_args(["--config", "local.yaml"]).frames == 30
    with pytest.raises(SystemExit):
        parser.parse_args([])


def test_probe_suppresses_rtsp_logger_credentials(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    raw_url = "rtsp://camera_user:camera_password@example.test:8554/live"
    config = SimpleNamespace(
        source=SimpleNamespace(
            type="rtsp",
            url=raw_url,
            path="unused-fallback",
            reconnect_retries=1,
            reconnect_delay_ms=0,
        )
    )
    rtsp_logger = logging.getLogger("eovrt_media.sources.rtsp_source")
    original_disabled = rtsp_logger.disabled
    rtsp_logger.disabled = False

    class FakeRtspSource:
        def __init__(self, **_kwargs: object) -> None:
            pass

        def __iter__(self):
            rtsp_logger.warning("RTSP connection failed: %s", raw_url)
            raise ConnectionError("connection failed")

    monkeypatch.setattr(probe_rtsp, "load_run_config", lambda _path: config)
    monkeypatch.setattr(probe_rtsp, "RtspSource", FakeRtspSource)

    try:
        with pytest.raises(ConnectionError):
            probe_rtsp.probe(Path("dummy-config.yaml"), frames=1)

        assert raw_url not in caplog.text
        assert rtsp_logger.disabled is False
    finally:
        rtsp_logger.disabled = original_disabled
