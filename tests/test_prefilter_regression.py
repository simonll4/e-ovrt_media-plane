"""Compuerta de regresión final (spec 2026-07-15 §8): invariantes de
compatibilidad para las fuentes no-OAK-D (image_folder/video_file/rtsp).

Reutiliza el patrón de fixture de `tests/test_pipeline_mock.py` (config real +
MockDetector) sin tocar ese archivo. Verifica que una corrida image_folder +
Mock quede exactamente como antes de EN-2 / los knobs de latencia / la
telemetría capture_to_host: nada de esto se filtra a fuentes que no las usan.
"""

import json
from pathlib import Path

import cv2
import numpy as np
import pytest

from eovrt_media.config import load_run_config
from eovrt_media.runtime import run_pipeline


CONFIGS_DIR = Path(__file__).parent / "fixtures"


def _create_test_images(folder: Path, count: int = 3) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    for i in range(count):
        img = np.zeros((480, 640, 3), dtype=np.uint8)
        img[:] = (50 + i * 30, 100, 200)
        cv2.imwrite(str(folder / f"test_{i:03d}.jpg"), img)


@pytest.fixture
def mock_config(tmp_path):
    """Config de corrida con mock detector y datos temporales (misma receta
    que TestPipelineMock.mock_config en test_pipeline_mock.py)."""
    images_dir = tmp_path / "images"
    _create_test_images(images_dir, count=3)

    config = load_run_config(CONFIGS_DIR / "runs" / "gdino.yaml")

    config.model.adapter = "mock"
    config.model.name = "mock"
    config.source.path = str(images_dir)
    config.outputs.base_dir = str(tmp_path / "runs")
    config.outputs.run_dir = str(tmp_path / "runs")
    config.outputs.save_previews = True

    return config


class TestPrefilterRegressionInvariants:
    """§8: para fuentes sin prefilter/capture_to_host, la telemetría nueva
    debe quedar apagada/ausente exactamente como en EN-0."""

    def test_summary_prefilter_disabled(self, mock_config):
        run_id = run_pipeline(mock_config)
        run_dir = Path(mock_config.output.base_dir) / run_id
        summary = json.loads((run_dir / "summary.json").read_text())

        assert summary["prefilter"] == {"enabled": False}

    def test_summary_capture_to_host_absent(self, mock_config):
        run_id = run_pipeline(mock_config)
        run_dir = Path(mock_config.output.base_dir) / run_id
        summary = json.loads((run_dir / "summary.json").read_text())

        # SummarySink usa exclude_none=True: capture_to_host=None -> ausente.
        assert "capture_to_host" not in summary

    def test_metrics_capture_to_host_ms_null_or_absent(self, mock_config):
        run_id = run_pipeline(mock_config)
        run_dir = Path(mock_config.output.base_dir) / run_id

        lines = (run_dir / "metrics.jsonl").read_text().splitlines()
        assert len(lines) == 3
        for line in lines:
            metric = json.loads(line)
            # Ausente (exclude_none) o explícitamente null: ambas formas
            # comunican "no medible", nunca un número.
            assert metric.get("capture_to_host_ms") is None

    def test_detections_no_new_fields(self, mock_config):
        run_id = run_pipeline(mock_config)
        run_dir = Path(mock_config.output.base_dir) / run_id

        lines = (run_dir / "detections.jsonl").read_text().splitlines()
        assert len(lines) == 3
        for line in lines:
            event = json.loads(line)
            assert "capture_to_host_ms" not in event
            assert "prefilter" not in event
