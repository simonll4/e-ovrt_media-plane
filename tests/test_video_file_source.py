"""Tests para VideoFileSource."""

from pathlib import Path
import cv2
import numpy as np

from eovrt_media.sources import VideoFileSource


def _create_dummy_video(path: Path, frames: int = 10, fps: int = 30) -> None:
    """Crea un archivo de video dummy para pruebas."""
    fourcc = cv2.VideoWriter_fourcc(*'MJPG')
    writer = cv2.VideoWriter(str(path), fourcc, fps, (640, 480))
    for i in range(frames):
        img = np.zeros((480, 640, 3), dtype=np.uint8)
        img[:] = ((i * 5) % 256, 100, 200)
        writer.write(img)
    writer.release()


class TestVideoFileSource:
    def test_video_load_and_metadata(self, tmp_path):
        video_path = tmp_path / "test.avi"
        _create_dummy_video(video_path, frames=15, fps=30)

        source = VideoFileSource(video_path)
        assert source.width == 640
        assert source.height == 480
        assert source.fps == 30.0
        assert source.total_frames == 15
        assert len(source) == 15

    def test_video_every_n_sampling(self, tmp_path):
        video_path = tmp_path / "test.avi"
        _create_dummy_video(video_path, frames=15, fps=30)

        # Muestrear cada 3 frames
        source = VideoFileSource(video_path, every_n=3)
        assert len(source) == 5

        units = list(source)
        assert len(units) == 5
        assert units[0].frame_index == 0
        assert units[1].frame_index == 3
        assert units[4].frame_index == 12

    def test_video_target_fps_sampling(self, tmp_path):
        video_path = tmp_path / "test.avi"
        _create_dummy_video(video_path, frames=30, fps=30)  # 1 segundo de video

        # Muestrear a 10 FPS
        source = VideoFileSource(video_path, target_fps=10)
        assert len(source) == 10

        units = list(source)
        assert len(units) == 10
        assert units[0].frame_index == 0
        # 30 fps / 10 fps = step 3
        assert units[1].frame_index == 3

    def test_video_max_units_sampling(self, tmp_path):
        video_path = tmp_path / "test.avi"
        _create_dummy_video(video_path, frames=20, fps=10)

        # Muestrear máximo 5 frames
        source = VideoFileSource(video_path, max_units=5)
        assert len(source) == 5
        assert len(list(source)) == 5
