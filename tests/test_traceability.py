from __future__ import annotations

import json
from pathlib import Path

import cv2
import numpy as np

from eovrt_media.config import load_run_config
from eovrt_media.runtime import run_pipeline


CONFIGS_DIR = Path(__file__).parent.parent / "configs"


def _create_test_images(folder: Path, count: int = 3) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    for index in range(count):
        cv2.imwrite(str(folder / f"img_{index:03d}.jpg"), np.zeros((48, 64, 3), np.uint8))


def _mock_config(tmp_path: Path):
    images_dir = tmp_path / "images"
    _create_test_images(images_dir)
    config = load_run_config(CONFIGS_DIR / "runs" / "mock.yaml")
    config.source.path = str(images_dir)
    config.source.dataset_id = "test_dataset"
    config.source.view = "canonical_v2"
    config.source.split = "bench_test"
    config.source.vocabulary = ["person", "helmet"]
    config.outputs.base_dir = str(tmp_path / "runs")
    config.outputs.run_dir = str(tmp_path / "runs")
    config.outputs.save_previews = False
    return config


def _summary(config, run_id: str) -> dict:
    return json.loads((Path(config.outputs.base_dir) / run_id / "summary.json").read_text())


class TestRunDescriptor:
    def test_summary_contains_deployment_descriptor_and_metrics(self, tmp_path: Path):
        config = _mock_config(tmp_path)
        summary = _summary(config, run_pipeline(config))

        assert summary["schema_version"] == "media.summary.v2"
        assert summary["p99_latency_ms"] >= 0.0
        assert summary["units_dropped"] == 0
        descriptor = summary["run_descriptor"]
        assert descriptor["scenario"] == "DBE"
        assert descriptor["topology"] == "single_host"
        assert descriptor["transport"]["backend"] == "memory"
        assert descriptor["rate_control"]["policy"] == "deterministic"
        assert descriptor["source_kind"] == "pulleable"


class TestRunProvenance:
    def test_provenance_records_dataset_and_stable_fingerprint(self, tmp_path: Path):
        config = _mock_config(tmp_path)
        run_id_1 = run_pipeline(config)
        provenance_1 = json.loads(
            (Path(config.outputs.base_dir) / run_id_1 / "run_provenance.json").read_text()
        )

        config.outputs.base_dir = str(tmp_path / "runs-2")
        config.outputs.run_dir = str(tmp_path / "runs-2")
        run_id_2 = run_pipeline(config)
        provenance_2 = json.loads(
            (Path(config.outputs.base_dir) / run_id_2 / "run_provenance.json").read_text()
        )

        assert provenance_1["dataset_id"] == "test_dataset"
        assert provenance_1["view"] == "canonical_v2"
        assert provenance_1["split"] == "bench_test"
        assert len(provenance_1["source_fingerprint"]) == 64
        assert provenance_1["source_fingerprint"] == provenance_2["source_fingerprint"]


class TestAutoNamingAndMetricVersion:
    def test_auto_run_id_encodes_deployment_axes(self, tmp_path: Path):
        config = _mock_config(tmp_path)
        run_id = run_pipeline(config)
        assert "dbe" in run_id
        assert "mock" in run_id
        assert "deterministic" in run_id

    def test_metrics_are_versioned_and_include_normalize_latency(self, tmp_path: Path):
        config = _mock_config(tmp_path)
        run_id = run_pipeline(config)
        metrics_path = Path(config.outputs.base_dir) / run_id / "metrics.jsonl"
        metric = json.loads(metrics_path.read_text().splitlines()[0])
        assert metric["schema_version"] == "media.metric.v2"
        assert metric["latency_normalize_ms"] >= 0.0

    def test_custom_run_id_is_preserved(self, tmp_path: Path):
        config = _mock_config(tmp_path)
        config.run.id = "my_custom_run_42"
        run_id = run_pipeline(config)
        assert run_id == "my_custom_run_42"
        run_dir = Path(config.outputs.base_dir) / "my_custom_run_42"
        assert run_dir.exists()


class TestBoundedFreshnessTraceability:
    def test_units_dropped_field_present_in_bounded_freshness_summary(self, tmp_path: Path):
        config = _mock_config(tmp_path)
        config.rate_control.policy = "bounded_freshness"
        config.rate_control.buffer_size = 2
        run_id = run_pipeline(config)
        summary = _summary(config, run_id)
        assert "units_dropped" in summary
        assert summary["units_dropped"] >= 0
        total = summary["units_processed"] + summary["units_failed"] + summary["units_dropped"]
        assert total <= 3  # source count from _mock_config
