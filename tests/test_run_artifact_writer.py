"""Tests de RunArtifactWriter: manifest, summary con desgloses y compare-runs."""

import json
from pathlib import Path

import cv2
import numpy as np
import pytest
from typer.testing import CliRunner

from eovrt_media.cli import app, _collect_summaries
from eovrt_media.config import load_run_config
from eovrt_media.runtime import run_pipeline


CONFIGS_DIR = Path(__file__).parent.parent / "configs"


def _create_test_images(folder: Path, count: int = 3) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    for i in range(count):
        img = np.zeros((480, 640, 3), dtype=np.uint8)
        img[:] = (50 + i * 30, 100, 200)
        cv2.imwrite(str(folder / f"test_{i:03d}.jpg"), img)


@pytest.fixture
def completed_run(tmp_path):
    """Ejecuta una corrida mock completa y devuelve (run_dir, summary_dict)."""
    images_dir = tmp_path / "images"
    _create_test_images(images_dir, count=3)

    config = load_run_config(CONFIGS_DIR / "runs" / "mock.yaml")
    config.model.adapter = "mock"
    config.model.name = "mock"
    config.source.path = str(images_dir)
    config.outputs.base_dir = str(tmp_path / "runs")
    config.outputs.run_dir = str(tmp_path / "runs")

    run_id = run_pipeline(config)
    run_dir = Path(config.outputs.run_dir) / run_id

    with open(run_dir / "summary.json") as f:
        summary = json.load(f)

    return run_dir, summary


class TestRunManifest:
    def test_manifest_exists(self, completed_run):
        run_dir, _ = completed_run
        assert (run_dir / "run_manifest.json").exists()

    def test_manifest_fields(self, completed_run):
        run_dir, summary = completed_run
        with open(run_dir / "run_manifest.json") as f:
            manifest = json.load(f)

        assert manifest["run_id"] == summary["run_id"]
        assert manifest["started_at"]
        assert manifest["finished_at"]
        assert manifest["output_dir"] == str(run_dir)
        assert "code_version" in manifest

    def test_manifest_lists_generated_files(self, completed_run):
        run_dir, _ = completed_run
        with open(run_dir / "run_manifest.json") as f:
            manifest = json.load(f)

        files = manifest["generated_files"]
        for expected in ("detections.jsonl", "metrics.jsonl", "summary.json"):
            assert expected in files
        assert "run_manifest.json" not in files


class TestSummaryBreakdowns:
    def test_detections_by_label_present(self, completed_run):
        _, summary = completed_run
        assert "detections_by_label" in summary
        assert isinstance(summary["detections_by_label"], dict)

    def test_by_label_sums_to_total(self, completed_run):
        _, summary = completed_run
        assert sum(summary["detections_by_label"].values()) == summary["total_detections"]

    def test_by_prompt_id_sums_to_total(self, completed_run):
        _, summary = completed_run
        assert sum(summary["detections_by_prompt_id"].values()) == summary["total_detections"]

    def test_gpu_peak_field_present(self, completed_run):
        _, summary = completed_run
        # En CPU debe ser 0.0, pero el campo tiene que existir
        assert "gpu_memory_peak_mb" in summary
        assert summary["gpu_memory_peak_mb"] >= 0.0


class TestCompareRuns:
    def test_collect_summaries_from_root(self, completed_run):
        run_dir, summary = completed_run
        summaries = _collect_summaries([run_dir.parent])
        assert len(summaries) == 1
        assert summaries[0]["run_id"] == summary["run_id"]

    def test_collect_summaries_from_run_dir(self, completed_run):
        run_dir, summary = completed_run
        summaries = _collect_summaries([run_dir])
        assert len(summaries) == 1
        assert summaries[0]["run_id"] == summary["run_id"]

    def test_cli_compare_runs(self, completed_run):
        run_dir, summary = completed_run
        runner = CliRunner()
        result = runner.invoke(app, ["compare-runs", str(run_dir.parent)])
        assert result.exit_code == 0
        assert summary["run_id"] in result.output
