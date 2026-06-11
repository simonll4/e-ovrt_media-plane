# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Setup
python3.11 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# Models
make download-models                            # fetches GDINO tiny+base, MM-GDINO t/b/l, YOLOE-26 s/m/l/x

# Run
make run-gdino                                  # Grounding DINO sample run
make run-yoloe                                  # YOLOE sample run
eovrt-media run --config configs/runs/<file>.yaml   # direct CLI

# CLI utilities
eovrt-media validate-config --config <yaml>
eovrt-media inspect-run runs/<run_id>
eovrt-media compare-runs runs/                  # comparison table across runs

# Test
make test                                       # pytest -q
pytest tests/test_pipeline_mock.py              # single module
pytest -xvs                                     # verbose, stop on first failure

# Lint
make lint                                       # ruff check src tests
```

## Architecture

Python pipeline for open-vocabulary object detection (OVD). All behavior is config-driven via YAML; no hardcoded paths or thresholds.

**Config catalogs**: run configs in `configs/runs/` compose catalog entries by reference — `model.ref` → `configs/models/<family>/<variant>.yaml`, `source.ref` → `configs/datasets/<name>.yaml`, `prompts.ref` → `configs/prompts/<name>.yaml`. Inline fields in the run config override catalog values; ref resolution lives in `config/loader.py`. Weights live in `models/<family>/{original,finetuned/<tag>}/`, one catalog entry per weight. See `configs/README.md`.

**Execution path**: `cli.py` → `runtime/pipeline.py:run_pipeline()` → per-unit loop (read → preprocess → inference → postprocess → write)

**Key abstractions**:
- `BaseDetectorAdapter` (`models/base.py`) — plugin interface for inference; register new adapters in `models/__init__.py:create_adapter()`
- `BaseSource` (`sources/base.py`) — yields `VisualUnit` objects; two implementations: `ImageFolderSource`, `VideoFileSource`
- `RunContext` (`runtime/run_context.py`) — stateful execution context (run_id, unit counts, timing); owns the output directory
- `RunArtifactWriter` (`sinks/run_artifact_writer.py`) — persists to `runs/<run_id>/`: `detections.jsonl`, `metrics.jsonl`, `errors.jsonl`, `summary.json`, `previews/`

**Data contracts** (`contracts/`) — Pydantic models flow through the pipeline: `VisualUnit` → `RawDetection` → `Detection` → `DetectionEvent`/`MetricSample` for persistence.

**Error handling**: each pipeline stage catches independently; failures are logged to `errors.jsonl` and execution continues to the next unit.

**Metrics**: sub-stage latency tracked at microsecond granularity via `metrics/timers.py`; aggregated (p95, p99, FPS) in `metrics/collector.py`.

## Testing

`MockDetector` (`models/mock_detector.py`) enables full end-to-end pipeline tests without loading real model weights — use it for integration tests. Tests live in `tests/`; fixtures in `tests/conftest.py`.

## Out of scope

This pipeline does not implement: risk rules, alert generation, multi-object tracking (MOT), zones/geofences, control plane logic, UI, or message queues.
