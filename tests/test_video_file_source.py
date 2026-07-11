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

    def test_iter_embebe_pixel_data_decodificado(self, tmp_path):
        # Decodificación secuencial: cada unidad lleva el frame BGR embebido,
        # así image_loader no reabre el video (open+seek) por cada frame.
        video_path = tmp_path / "test.avi"
        _create_dummy_video(video_path, frames=6, fps=30)

        units = list(VideoFileSource(video_path))

        assert len(units) == 6
        for unit in units:
            assert unit.pixel_data is not None
            assert unit.pixel_data.dtype == np.uint8
            assert unit.pixel_data.shape == (480, 640, 3)

    def test_source_id_explicito_se_estampa_sin_extension(self, tmp_path):
        # GT del banco de clips matchea alertas por source_id == clip_id
        # (p.ej. "cb_b01_p7"); sin el knob, VisualUnit derivaba el basename
        # con extensión ("cb_b01_p7.mp4") y el join nunca cerraba.
        video_path = tmp_path / "cb_b01_p7.mp4"
        _create_dummy_video(video_path, frames=6, fps=30)

        units = list(VideoFileSource(video_path, source_id="cb_b01_p7", max_units=2))

        assert len(units) == 2
        for unit in units:
            assert unit.source_id == "cb_b01_p7"

    def test_sin_source_id_comportamiento_actual_basename_con_extension(self, tmp_path):
        video_path = tmp_path / "cb_b01_p7.mp4"
        _create_dummy_video(video_path, frames=6, fps=30)

        units = list(VideoFileSource(video_path, max_units=2))

        assert len(units) == 2
        for unit in units:
            assert unit.source_id == "cb_b01_p7.mp4"

    def test_pixel_data_corresponde_al_frame_muestreado(self, tmp_path):
        # Con every_n=3 el pixel_data de la unidad i debe ser el frame 3*i del
        # video, no el siguiente disponible (el dummy pinta B=(i*5)%256 en BGR).
        video_path = tmp_path / "test.avi"
        _create_dummy_video(video_path, frames=15, fps=30)

        units = list(VideoFileSource(video_path, every_n=3))

        assert [u.frame_index for u in units] == [0, 3, 6, 9, 12]
        for unit in units:
            expected_blue = (unit.frame_index * 5) % 256
            got_blue = float(unit.pixel_data[:, :, 0].mean())
            # MJPG es lossy: tolerancia amplia pero suficiente para distinguir
            # frames (los valores esperados difieren en 15).
            assert abs(got_blue - expected_blue) < 6, (
                f"frame {unit.frame_index}: blue medio {got_blue} != {expected_blue}"
            )
