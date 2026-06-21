"""Tests del pipeline completo con MockDetector."""

import json
from pathlib import Path

import cv2
import numpy as np
import pytest

from eovrt_media.config import load_run_config
from eovrt_media.contracts.detection import RawDetection
from eovrt_media.models.mock_detector import MockDetectorAdapter
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
        config = load_run_config(CONFIGS_DIR / "runs" / "gdino.yaml")

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

    def test_creates_annotated_preview(self, mock_config):
        """Las detecciones generan al menos una preview anotada legible."""
        run_id = run_pipeline(mock_config)
        run_dir = Path(mock_config.output.base_dir) / run_id

        previews_dir = run_dir / "previews"
        assert previews_dir.exists()
        previews = list(previews_dir.glob("*.preview.jpg"))
        assert previews
        assert cv2.imread(str(previews[0])) is not None

    def test_detections_reprojected_to_original_image_space(self, tmp_path, monkeypatch):
        """Boxes de adapter.forward() se reproyectan del espacio-modelo al espacio original.

        Imagen 100H×200W con target 640×640 letterbox:
          scale=3.2, pad_y=160, pad_x=0
          box modelo (200,320,400,440) → original (62.5,50,125,87.5)
          bbox_norm ≈ (0.3125, 0.5, 0.625, 0.875)

        Sin reproyección, y1=320/100=3.2 se recortaría a 1.0 (incorrecta).
        """
        images_dir = tmp_path / "nonsquare"
        images_dir.mkdir()
        for i in range(3):
            cv2.imwrite(str(images_dir / f"img_{i:03d}.jpg"), np.zeros((100, 200, 3), np.uint8))

        def fixed_forward(self, unit, prompts):
            return [RawDetection(label=prompts[0], score=0.9, box_xyxy=[200.0, 320.0, 400.0, 440.0])]

        monkeypatch.setattr(MockDetectorAdapter, "forward", fixed_forward)

        config = load_run_config(CONFIGS_DIR / "runs" / "mock.yaml")
        config.source.path = str(images_dir)
        config.outputs.base_dir = str(tmp_path / "runs")
        config.outputs.run_dir = str(tmp_path / "runs")
        config.outputs.save_previews = False

        run_id = run_pipeline(config)
        detections_path = Path(config.outputs.base_dir) / run_id / "detections.jsonl"
        events = [json.loads(line) for line in detections_path.read_text().splitlines()]

        assert all(len(e["detections"]) == 1 for e in events)

        for event in events:
            det = event["detections"][0]
            norm = det["bbox_norm_xyxy"]
            # Con reproyección correcta: ~(0.3125, 0.5, 0.625, 0.875)
            # Sin reproyección: y1=320/100=3.2 → clampado a 1.0
            assert norm[1] < 1.0, f"y1_norm={norm[1]:.4f}: parece sin reproyección (debería ser ~0.5)"
            assert norm[3] < 1.0, f"y2_norm={norm[3]:.4f}: parece sin reproyección (debería ser ~0.875)"
            assert pytest.approx(norm[0], abs=0.01) == 0.3125
            assert pytest.approx(norm[1], abs=0.01) == 0.5
            assert pytest.approx(norm[2], abs=0.01) == 0.625
            assert pytest.approx(norm[3], abs=0.01) == 0.875
