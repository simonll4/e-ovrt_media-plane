"""capture_to_host_ms: contrato aditivo y agregación p50/p95 (spec §7.3, §8.4)."""
from __future__ import annotations

from pathlib import Path

import numpy as np

from eovrt_media.config import load_run_config
from eovrt_media.contracts import VisualUnit
from eovrt_media.contracts.metrics import MetricSample
from eovrt_media.contracts.normalized_unit import PayloadFormat
from eovrt_media.models.base import ModelInputSpec
from eovrt_media.preprocessing.normalizer import normalize_spatial
from eovrt_media.runtime.run_context import RunContext
from eovrt_media.sinks.run_artifact_writer import RunArtifactWriter

CONFIGS_DIR = Path(__file__).parent / "fixtures"


def _spec_from_existing_tests() -> ModelInputSpec:
    return ModelInputSpec(target_size=(16, 16))


def _payload_format() -> PayloadFormat:
    return PayloadFormat.UINT8_RGB


def test_visual_unit_field_is_optional_and_defaults_none():
    unit = VisualUnit(unit_id="u", source_type="image", width=8, height=8)
    assert unit.capture_to_host_ms is None  # §8: aditivo, None para otras fuentes


def test_metric_sample_field_is_optional():
    m = MetricSample(run_id="r", unit_id="u")
    assert m.capture_to_host_ms is None


def test_normalize_spatial_copies_capture_to_host_ms():
    unit = VisualUnit(
        unit_id="u", source_type="video_frame", width=16, height=16,
        pixel_data=np.zeros((16, 16, 3), dtype=np.uint8),
        capture_to_host_ms=37.5,
    )
    normalized = normalize_spatial(unit, _spec_from_existing_tests(), _payload_format())
    assert normalized.capture_to_host_ms == 37.5


def test_write_summary_aggregates_p50_p95(tmp_path):
    config = load_run_config(CONFIGS_DIR / "runs" / "mock.yaml")
    config.model.adapter = "mock"
    config.model.name = "mock"
    config.outputs.base_dir = str(tmp_path / "runs")
    config.outputs.run_dir = str(tmp_path / "runs")

    context = RunContext(config)
    context.capture_to_host_samples = [10.0, 20.0, 30.0, 40.0]
    writer = RunArtifactWriter(context)
    writer.write_summary()

    import json

    with open(context.run_dir / "summary.json") as f:
        summary = json.load(f)

    assert summary["capture_to_host"] == {"p50_ms": 30.0, "p95_ms": 40.0, "samples": 4}


def test_write_summary_capture_to_host_none_when_no_samples(tmp_path):
    config = load_run_config(CONFIGS_DIR / "runs" / "mock.yaml")
    config.model.adapter = "mock"
    config.model.name = "mock"
    config.outputs.base_dir = str(tmp_path / "runs")
    config.outputs.run_dir = str(tmp_path / "runs")

    context = RunContext(config)
    assert context.capture_to_host_samples == []
    writer = RunArtifactWriter(context)
    writer.write_summary()

    import json

    with open(context.run_dir / "summary.json") as f:
        summary = json.load(f)

    # SummarySink serializa con exclude_none=True (comportamiento existente,
    # compartido por todos los campos None de RunSummary): la clave no
    # aparece en el JSON en vez de aparecer con valor null.
    assert summary.get("capture_to_host") is None
