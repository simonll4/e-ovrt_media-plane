from __future__ import annotations

import json
import threading
from pathlib import Path

import cv2
import numpy as np

from eovrt_media.config import load_run_config
from eovrt_media.models.mock_detector import MockDetectorAdapter
from eovrt_media.runtime import run_pipeline


CONFIGS_DIR = Path(__file__).parent.parent / "configs"


def _create_test_images(folder: Path, count: int = 5) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    for index in range(count):
        image = np.zeros((480, 640, 3), dtype=np.uint8)
        image[:] = (50 + index * 30, 100, 200)
        cv2.imwrite(str(folder / f"test_{index:03d}.jpg"), image)


def _mock_config(tmp_path: Path):
    images_dir = tmp_path / "images"
    _create_test_images(images_dir)
    config = load_run_config(CONFIGS_DIR / "runs" / "mock.yaml")
    config.source.path = str(images_dir)
    config.outputs.base_dir = str(tmp_path / "runs")
    config.outputs.run_dir = str(tmp_path / "runs")
    config.outputs.save_previews = False
    return config


class TestProducerConsumerPipeline:
    def test_pipeline_calls_forward_with_normalized_units(self, tmp_path: Path, monkeypatch):
        observed_units = []
        observed_threads = []

        def forward(self, unit, prompts):
            observed_units.append(unit)
            observed_threads.append(threading.current_thread().name)
            return self.predict_image_from_normalized(unit, prompts)

        def predict_image_from_normalized(self, unit, prompts):
            from PIL import Image

            return self.predict(Image.fromarray(unit.payload), prompts)

        monkeypatch.setattr(MockDetectorAdapter, "forward", forward, raising=False)
        monkeypatch.setattr(
            MockDetectorAdapter,
            "predict_image_from_normalized",
            predict_image_from_normalized,
            raising=False,
        )

        run_pipeline(_mock_config(tmp_path))

        assert len(observed_units) == 5
        assert all(unit.target_size == (640, 640) for unit in observed_units)
        assert observed_threads == ["MainThread"] * 5

    def test_deterministic_two_runs_have_identical_detections(self, tmp_path: Path):
        config = _mock_config(tmp_path)
        run_id_1 = run_pipeline(config)
        detections_1 = (Path(config.outputs.base_dir) / run_id_1 / "detections.jsonl").read_text()

        config.outputs.base_dir = str(tmp_path / "runs-2")
        config.outputs.run_dir = str(tmp_path / "runs-2")
        run_id_2 = run_pipeline(config)
        detections_2 = (Path(config.outputs.base_dir) / run_id_2 / "detections.jsonl").read_text()

        events_1 = [json.loads(line)["detections"] for line in detections_1.splitlines()]
        events_2 = [json.loads(line)["detections"] for line in detections_2.splitlines()]
        assert events_1 == events_2

    def test_clean_shutdown_processes_all_units(self, tmp_path: Path):
        config = _mock_config(tmp_path)
        run_id = run_pipeline(config)
        summary = json.loads(
            (Path(config.outputs.base_dir) / run_id / "summary.json").read_text()
        )
        assert summary["units_processed"] == 5
        assert summary["units_failed"] == 0

    def test_rate_gate_applies_stride(self, tmp_path: Path):
        config = _mock_config(tmp_path)
        config.rate_control.stride = 2
        run_id = run_pipeline(config)
        summary = json.loads(
            (Path(config.outputs.base_dir) / run_id / "summary.json").read_text()
        )
        assert summary["units_processed"] == 3
