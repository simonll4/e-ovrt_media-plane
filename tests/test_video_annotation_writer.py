"""Tests for the annotated-video sink."""

from __future__ import annotations

import shutil
import subprocess

import cv2
import numpy as np
import pytest

from eovrt_media.contracts import Detection
from eovrt_media.sinks.video_annotation_writer import VideoAnnotationWriter


def _codec_name(path) -> str:
    out = subprocess.run(
        [
            "ffprobe", "-v", "error", "-select_streams", "v:0",
            "-show_entries", "stream=codec_name", "-of", "csv=p=0", str(path),
        ],
        capture_output=True, text=True,
    )
    return out.stdout.strip()


def _detection() -> Detection:
    return Detection(
        label="person",
        confidence=0.9,
        bbox_xyxy=[2.0, 2.0, 8.0, 8.0],
        bbox_norm_xyxy=[0.1, 0.1, 0.4, 0.4],
    )


def _frame(color=(255, 0, 0), size=(20, 20)) -> np.ndarray:
    h, w = size
    return np.full((h, w, 3), color, dtype=np.uint8)


def _count_frames(path) -> int:
    cap = cv2.VideoCapture(str(path))
    count = 0
    while True:
        ok, _ = cap.read()
        if not ok:
            break
        count += 1
    cap.release()
    return count


def test_infers_fps_from_timestamps_and_writes_all_frames(tmp_path):
    out = tmp_path / "annotated.mp4"
    writer = VideoAnnotationWriter(out)

    for i, ts in enumerate([0.0, 200.0, 400.0]):
        writer.add(_frame(), [_detection()], timestamp_ms=ts)
    writer.close()

    assert out.exists() and out.stat().st_size > 0
    assert _count_frames(out) == 3
    cap = cv2.VideoCapture(str(out))
    assert abs(cap.get(cv2.CAP_PROP_FPS) - 5.0) < 0.6  # 1000/200ms
    cap.release()


def test_fps_override_is_respected(tmp_path):
    out = tmp_path / "annotated.mp4"
    writer = VideoAnnotationWriter(out, fps_override=12.0)

    for ts in [0.0, 200.0]:
        writer.add(_frame(), [_detection()], timestamp_ms=ts)
    writer.close()

    cap = cv2.VideoCapture(str(out))
    assert abs(cap.get(cv2.CAP_PROP_FPS) - 12.0) < 0.6
    cap.release()


def test_single_frame_uses_default_fps(tmp_path):
    out = tmp_path / "annotated.mp4"
    writer = VideoAnnotationWriter(out, default_fps=8.0)

    writer.add(_frame(), [_detection()], timestamp_ms=0.0)
    writer.close()

    assert out.exists() and out.stat().st_size > 0
    assert _count_frames(out) == 1
    cap = cv2.VideoCapture(str(out))
    assert abs(cap.get(cv2.CAP_PROP_FPS) - 8.0) < 0.6
    cap.release()


def test_mismatched_frame_size_is_resized(tmp_path):
    out = tmp_path / "annotated.mp4"
    writer = VideoAnnotationWriter(out)

    writer.add(_frame(size=(20, 20)), [_detection()], timestamp_ms=0.0)
    writer.add(_frame(size=(30, 40)), [_detection()], timestamp_ms=100.0)
    writer.close()

    assert _count_frames(out) == 2
    cap = cv2.VideoCapture(str(out))
    assert int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)) == 20
    assert int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)) == 20
    cap.release()


@pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="requiere ffmpeg/ffprobe para transcodificar y verificar el codec H.264",
)
def test_output_is_h264_when_ffmpeg_available(tmp_path):
    out = tmp_path / "annotated.mp4"
    writer = VideoAnnotationWriter(out)

    for ts in [0.0, 100.0, 200.0]:
        writer.add(_frame(), [_detection()], timestamp_ms=ts)
    writer.close()

    assert out.exists() and out.stat().st_size > 0
    assert _codec_name(out) == "h264"
    assert _count_frames(out) == 3


def test_close_is_idempotent_and_no_frames_writes_nothing(tmp_path):
    out = tmp_path / "annotated.mp4"
    writer = VideoAnnotationWriter(out)
    writer.close()
    writer.close()
    assert not out.exists()
