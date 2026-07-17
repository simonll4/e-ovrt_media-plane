"""Bloque prefilter del summary (spec §6/§8): registro de descartes EN-2."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from eovrt_media.config import load_run_config
from eovrt_media.config.schemas import OakDPrefilterConfig
from eovrt_media.runtime.run_context import RunContext
from eovrt_media.sinks.run_artifact_writer import RunArtifactWriter

CONFIGS_DIR = Path(__file__).parent / "fixtures"


def _read_summary(run_dir):
    return json.loads((run_dir / "summary.json").read_text())


@pytest.fixture
def make_context_and_writer(tmp_path):
    def _make(source_overrides: dict | None = None, topology_mode: str | None = None):
        config = load_run_config(CONFIGS_DIR / "runs" / "mock.yaml")
        config.model.adapter = "mock"
        config.model.name = "mock"
        config.outputs.base_dir = str(tmp_path / "runs")
        config.outputs.run_dir = str(tmp_path / "runs")
        if source_overrides:
            merged = {**config.source.model_dump(), **source_overrides}
            config.source = type(config.source)(**merged)
        if topology_mode:
            config.topology.mode = topology_mode

        context = RunContext(config)
        writer = RunArtifactWriter(context)
        tracker = None
        return context, writer, tracker

    return _make


def test_summary_without_prefilter_reports_enabled_false(make_context_and_writer):
    # Fuente image_folder (default): el bloque existe y es {"enabled": false}.
    ctx, writer, tracker = make_context_and_writer()
    writer.write_summary(tracker)
    assert _read_summary(ctx.run_dir)["prefilter"] == {"enabled": False}


def test_summary_with_prefilter_includes_config_and_counters(make_context_and_writer):
    counters = {"seen": 100, "forwarded": 40, "dropped_no_person": 60,
                "forwarded_by_reason": {"person": 30, "heartbeat": 8,
                                         "failopen": 0, "warmup": 2},
                "nn_results": 95}
    ctx, writer, tracker = make_context_and_writer(
        source_overrides={"type": "oak_d", "url": "192.168.1.50",
                          "prefilter": OakDPrefilterConfig(enabled=True).model_dump()},
    )
    ctx.prefilter_stats = counters
    ctx.prefilter_stats_age_s = 1.2
    writer.write_summary(tracker)
    block = _read_summary(ctx.run_dir)["prefilter"]
    assert block["enabled"] is True
    assert block["counters_available"] is True
    assert block["counters"] == counters
    assert block["stats_stale"] is False
    assert block["confidence"] == 0.25 and block["heartbeat_interval_ms"] == 2000


def test_summary_marks_stale_stats(make_context_and_writer):
    ctx, writer, tracker = make_context_and_writer(
        source_overrides={"type": "oak_d", "url": "192.168.1.50",
                          "prefilter": OakDPrefilterConfig(enabled=True).model_dump()},
    )
    ctx.prefilter_stats = {"seen": 1, "forwarded": 1, "dropped_no_person": 0,
                           "forwarded_by_reason": {}, "nn_results": 1}
    ctx.prefilter_stats_age_s = 42.0
    writer.write_summary(tracker)
    assert _read_summary(ctx.run_dir)["prefilter"]["stats_stale"] is True


def test_summary_two_node_declares_counters_unavailable(make_context_and_writer):
    ctx, writer, tracker = make_context_and_writer(
        source_overrides={"type": "oak_d", "url": "192.168.1.50",
                          "prefilter": OakDPrefilterConfig(enabled=True).model_dump()},
        topology_mode="two_node",
    )
    writer.write_summary(tracker)
    block = _read_summary(ctx.run_dir)["prefilter"]
    assert block["counters_available"] is False
    assert block["reason"] == "two_node_v1"
    assert "counters" not in block
