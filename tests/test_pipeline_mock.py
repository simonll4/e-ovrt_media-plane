"""Tests del pipeline completo con MockDetector."""

import json
from pathlib import Path

import cv2
import numpy as np
import pytest

from eovrt_media.config import load_run_config
from eovrt_media.runtime import run_pipeline


CONFIGS_DIR = Path(__file__).parent.parent / "configs"


def _create_test_images(folder: Path, count: int = 3) -> None:
    """Crea imágenes de prueba en la carpeta indicada."""
    folder.mkdir(parents=True, exist_ok=True)
    for i in range(count):
        img = np.zeros((480, 640, 3), dtype=np.uint8)
        img[:] = (50 + i * 30, 100, 200)
        cv2.imwrite(str(folder / f"test_{i:03d}.jpg"), img)


class TestPipelineMock:
    """Tests del pipeline usando el detector mock."""

    @pytest.fixture
    def mock_config(self, tmp_path):
        """Crea una configuración de corrida con mock detector y datos temporales."""
        # Crear imágenes de prueba
        images_dir = tmp_path / "images"
        _create_test_images(images_dir, count=3)

        # Cargar un config real y modificar para usar mock
        config = load_run_config(CONFIGS_DIR / "dbe_cr01_cr02_grounding_dino.yaml")

        # Override para testing
        config.model.adapter = "mock"
        config.source.path = str(images_dir)
        config.outputs.base_dir = str(tmp_path / "runs")
        config.outputs.run_dir = str(tmp_path / "runs")
        config.outputs.save_previews = True

        return config

    def test_pipeline_runs(self, mock_config):
        """El pipeline completa sin errores."""
        run_id = run_pipeline(mock_config)
        assert run_id is not None
        assert len(run_id) > 0

    def test_creates_run_directory(self, mock_config):
        """Se crea el directorio de la corrida."""
        run_id = run_pipeline(mock_config)
        run_dir = Path(mock_config.output.base_dir) / run_id
        assert run_dir.exists()
        assert run_dir.is_dir()

    def test_creates_detections_jsonl(self, mock_config):
        """Se genera detections.jsonl con eventos válidos."""
        run_id = run_pipeline(mock_config)
        run_dir = Path(mock_config.output.base_dir) / run_id

        jsonl_path = run_dir / "detections.jsonl"
        assert jsonl_path.exists()

        with open(jsonl_path) as f:
            lines = f.readlines()

        assert len(lines) == 3  # una línea por imagen

        # Validar estructura del primer evento
        event = json.loads(lines[0])
        assert "run_id" in event
        assert "unit_id" in event
        assert "detections" in event
        assert "timing_ms" in event
        assert isinstance(event["detections"], list)

    def test_creates_summary_json(self, mock_config):
        """Se genera summary.json con métricas válidas."""
        run_id = run_pipeline(mock_config)
        run_dir = Path(mock_config.output.base_dir) / run_id

        summary_path = run_dir / "summary.json"
        assert summary_path.exists()

        with open(summary_path) as f:
            summary = json.load(f)

        assert summary["run_id"] == run_id
        assert summary["scenario"] == "DBE"
        assert summary["model_adapter"] == "mock"
        assert summary["units_processed"] == 3
        assert summary["units_failed"] == 0
        assert summary["source_count"] == 3
        assert "avg_latency_ms" in summary
        assert "p50_latency_ms" in summary
        assert "p95_latency_ms" in summary

    def test_creates_metrics_jsonl(self, mock_config):
        """Se genera metrics.jsonl con una línea por imagen."""
        run_id = run_pipeline(mock_config)
        run_dir = Path(mock_config.output.base_dir) / run_id

        metrics_path = run_dir / "metrics.jsonl"
        assert metrics_path.exists()

        with open(metrics_path) as f:
            lines = f.readlines()

        assert len(lines) == 3

        metric = json.loads(lines[0])
        assert "inference_ms" in metric
        assert "total_ms" in metric
        assert "detection_count" in metric

    def test_creates_effective_config(self, mock_config):
        """Se guarda la configuración efectiva."""
        run_id = run_pipeline(mock_config)
        run_dir = Path(mock_config.output.base_dir) / run_id

        config_path = run_dir / "effective_config.yaml"
        assert config_path.exists()

    def test_creates_previews(self, mock_config):
        """Se generan previews anotadas."""
        run_id = run_pipeline(mock_config)
        run_dir = Path(mock_config.output.base_dir) / run_id

        previews_dir = run_dir / "previews"
        assert previews_dir.exists()
        # Puede haber 0 previews si el mock no generó detecciones para alguna imagen,
        # pero al menos el directorio debe existir.
