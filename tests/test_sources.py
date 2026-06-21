"""Tests para ImageFolderSource."""

from pathlib import Path

import cv2
import numpy as np
import pytest

from eovrt_media.sources import ImageFolderSource


def _create_test_image(path: Path, width: int = 640, height: int = 480) -> None:
    """Crea una imagen de prueba sólida."""
    img = np.zeros((height, width, 3), dtype=np.uint8)
    img[:] = (100, 150, 200)  # color sólido
    cv2.imwrite(str(path), img)


class TestImageFolderSource:
    def test_read_images(self, tmp_path):
        # Crear imágenes de prueba
        for i in range(3):
            _create_test_image(tmp_path / f"test_{i:03d}.jpg")

        source = ImageFolderSource(tmp_path)
        units = list(source)
        assert len(units) == 3

    def test_unit_properties(self, tmp_path):
        _create_test_image(tmp_path / "test.jpg", width=800, height=600)
        source = ImageFolderSource(tmp_path)
        units = list(source)
        assert len(units) == 1

        unit = units[0]
        assert unit.width == 800
        assert unit.height == 600
        assert unit.source_type == "image"
        assert unit.frame_index is None

    def test_sorted_order(self, tmp_path):
        for name in ["c.jpg", "a.jpg", "b.jpg"]:
            _create_test_image(tmp_path / name)

        source = ImageFolderSource(tmp_path)
        units = list(source)
        paths = [Path(u.source_path).name for u in units]
        assert paths == ["a.jpg", "b.jpg", "c.jpg"]

    def test_filter_extensions(self, tmp_path):
        _create_test_image(tmp_path / "test.jpg")
        _create_test_image(tmp_path / "test.png")
        (tmp_path / "readme.txt").write_text("not an image")

        source = ImageFolderSource(tmp_path, extensions=[".jpg"])
        units = list(source)
        assert len(units) == 1

    def test_empty_folder(self, tmp_path):
        source = ImageFolderSource(tmp_path)
        units = list(source)
        assert len(units) == 0

    def test_folder_not_found(self):
        with pytest.raises(FileNotFoundError):
            ImageFolderSource(Path("/nonexistent/path"))

    def test_len(self, tmp_path):
        for i in range(5):
            _create_test_image(tmp_path / f"img_{i}.jpg")

        source = ImageFolderSource(tmp_path)
        assert len(source) == 5

    def test_max_units_limits_iteration(self, tmp_path):
        for i in range(10):
            _create_test_image(tmp_path / f"img_{i:03d}.jpg")

        source = ImageFolderSource(tmp_path, max_units=3)
        units = list(source)
        assert len(units) == 3
        assert len(source) == 3
        # Debe quedarse con las primeras (orden alfabético)
        names = [Path(u.source_path).name for u in units]
        assert names == ["img_000.jpg", "img_001.jpg", "img_002.jpg"]

    def test_every_n_subsamples(self, tmp_path):
        for i in range(6):
            _create_test_image(tmp_path / f"img_{i:03d}.jpg")

        source = ImageFolderSource(tmp_path, every_n=2)
        names = [Path(u.source_path).name for u in source]
        assert names == ["img_000.jpg", "img_002.jpg", "img_004.jpg"]
        assert len(source) == 3

    def test_every_n_then_max_units(self, tmp_path):
        for i in range(10):
            _create_test_image(tmp_path / f"img_{i:03d}.jpg")

        # every_n=2 -> 0,2,4,6,8 ; luego cap a 2
        source = ImageFolderSource(tmp_path, every_n=2, max_units=2)
        names = [Path(u.source_path).name for u in source]
        assert names == ["img_000.jpg", "img_002.jpg"]
        assert len(source) == 2

    def test_no_sampling_by_default(self, tmp_path):
        for i in range(4):
            _create_test_image(tmp_path / f"img_{i}.jpg")

        source = ImageFolderSource(tmp_path)
        assert len(list(source)) == 4
        assert len(source) == 4
