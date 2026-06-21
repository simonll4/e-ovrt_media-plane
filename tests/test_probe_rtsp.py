"""Tests for the credential-safe RTSP probe script."""
from __future__ import annotations

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


def test_probe_rejects_zero_frames() -> None:
    with pytest.raises(ValueError, match="frames"):
        probe_rtsp.probe(Path("dummy-config.yaml"), frames=0)
