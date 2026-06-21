"""Tests de RtspSource usando un archivo de video como cámara simulada."""
from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
import pytest

from eovrt_media.sources.rtsp_source import RtspSource


@pytest.fixture
def fake_stream(tmp_path: Path) -> Path:
    """Genera un .mp4 de 5 frames que sustituye a la cámara RTSP."""
    video_path = tmp_path / "fake_stream.mp4"
    writer = cv2.VideoWriter(
        str(video_path), cv2.VideoWriter_fourcc(*"mp4v"), 5.0, (64, 48)
    )
    for i in range(5):
        frame = np.full((48, 64, 3), i * 10, dtype=np.uint8)
        writer.write(frame)
    writer.release()
    assert video_path.exists()
    return video_path


def _patch_capture(monkeypatch, video_path: Path) -> None:
    monkeypatch.setattr(
        RtspSource,
        "_open_capture",
        lambda self, url: cv2.VideoCapture(str(video_path)),
    )


class TestRtspSource:
    def test_yields_units_with_capture_timestamps(self, fake_stream, monkeypatch):
        _patch_capture(monkeypatch, fake_stream)
        source = RtspSource(url="rtsp://fake/stream", max_units=5)
        units = list(source)
        assert len(units) == 5
        assert all(u.source_type == "video_frame" for u in units)
        assert all(u.timestamp_ms is not None and u.timestamp_ms > 0 for u in units)
        # Los timestamps son de reloj de pared, no decrecientes.
        ts = [u.timestamp_ms for u in units]
        assert ts == sorted(ts)

    def test_len_is_indefinite(self, fake_stream, monkeypatch):
        # The brief specifies __len__() == -1 to signal "indefinite length".
        # Python 3.9+ enforces __len__ >= 0 at the C level (ValueError on -1)
        # and list() causes MemoryError on sys.maxsize.
        # Raising TypeError is the only CPython-compatible way to signal
        # "no defined length" while keeping list(source) functional.
        _patch_capture(monkeypatch, fake_stream)
        source = RtspSource(url="rtsp://fake/stream")
        with pytest.raises(TypeError, match="live stream"):
            len(source)

    def test_max_units_limits_iteration(self, fake_stream, monkeypatch):
        _patch_capture(monkeypatch, fake_stream)
        source = RtspSource(url="rtsp://fake/stream", max_units=3)
        assert len(list(source)) == 3

    def test_reconnects_before_giving_up(self, fake_stream, monkeypatch):
        attempts = {"count": 0}

        def flaky_open(self, url):
            attempts["count"] += 1
            if attempts["count"] < 3:
                cap = cv2.VideoCapture(str(tmp_nonexistent))  # no abre
                return cap
            return cv2.VideoCapture(str(fake_stream))

        tmp_nonexistent = fake_stream.parent / "missing.mp4"
        monkeypatch.setattr(RtspSource, "_open_capture", flaky_open)
        source = RtspSource(
            url="rtsp://fake/stream", reconnect_retries=5, reconnect_delay_ms=0, max_units=2
        )
        units = list(source)
        assert len(units) == 2
        assert attempts["count"] >= 3  # reintentó hasta conectar

    def test_raises_after_exhausting_retries(self, tmp_path, monkeypatch):
        missing = tmp_path / "missing.mp4"
        monkeypatch.setattr(
            RtspSource, "_open_capture", lambda self, url: cv2.VideoCapture(str(missing))
        )
        source = RtspSource(
            url="rtsp://fake/stream", reconnect_retries=2, reconnect_delay_ms=0
        )
        with pytest.raises(ConnectionError, match="RTSP"):
            list(source)
