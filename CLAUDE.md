# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Setup
python3.11 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# Models
make download-models                            # fetches GDINO tiny+base, MM-GDINO t/b/l, YOLOE-26 s/m/l/x

# Serve — el media-plane ya NO es un CLI: es un servicio HTTP/WS de un run activo.
# El CLI `eovrt-media` fue eliminado (Task 17); el pipeline se dispara vía la API.
EOVRT_MODEL_REF=mock make serve                 # uvicorn eovrt_media.service.app:create_app en :8080
make smoke                                      # curl a /healthz + /readyz

# Disparar una corrida vía la API (ejemplo mínimo, fuente image_folder + prompts inline)
curl -X POST http://localhost:8080/api/runs \
  -H "Content-Type: application/json" \
  -d '{
        "ingest": {"plugin": "image_folder", "config": {"path": "/path/to/images"}},
        "prompts": {"set_inline": {"person": "person"}, "active_ids": ["person"]}
      }'
# GET  /api/runs/{run_id}            — estado/resumen de la corrida
# WS   /api/runs/{run_id}/stream     — eventos en vivo (detecciones/métricas)
# POST /api/runs/{run_id}/stop       — detener la corrida activa

# Two-node topology (EBE distributed) — se sigue invocando en proceso, no vía CLI:
# runtime/two_node.py:run_node_a() / run_node_b(); ver tests/test_cli_two_node.py.

# Utilidades standalone (ex-subcomandos CLI), invocables como módulos:
python -m eovrt_media.tools.evaluate --run runs/<run_id> [--bench-coco ...] [--person-gt ...]
python -m eovrt_media.tools.inspect_runs inspect runs/<run_id>
python -m eovrt_media.tools.inspect_runs compare runs/          # tabla comparativa
python -m eovrt_media.tools.debug_run --source bench-val [...]  # campaña de debug
# CAVEAT: la ruta de dos-nodos-local de debug_run (run_two_node_local) NO funciona
# post-eliminación-del-CLI (spawnea el `eovrt_media.cli` borrado); ahora falla con un
# RuntimeError explícito. Pendiente de decisión en Fase 2 (docker-compose de dos nodos).

# Test
make test                                       # pytest -q
pytest tests/test_pipeline_mock.py              # single module
pytest -xvs                                     # verbose, stop on first failure

# Lint
make lint                                       # ruff check src tests
```

## Architecture

Python pipeline for open-vocabulary object detection (OVD). All behavior is config-driven via YAML; no hardcoded paths or thresholds.

**Config catalogs (dos raíces)**: los **manifiestos de corrida** y los **prompt sets** viven en el repo hermano `e-ovrt_experimental-setup` (`experiments/` y `prompts/`). El media-plane conserva los **catálogos de capacidades** `configs/models/` y `configs/datasets/`. Un manifiesto compone por referencia: `model.ref`/`source.ref` → catálogo del plano (autodescubierto repo-relative; override `--catalog-root`/`EOVRT_MEDIA_CATALOG_ROOT`); `prompts.ref` → `experimental-setup/prompts/<name>.yaml` (raíz del experimento, descubierta subiendo hasta el dir con `prompts/`). Inline fields override catalog values; resolución en `config/loader.py` (`find_plane_catalog_root` + `find_experiment_root`). Los tests usan `tests/fixtures/{runs,prompts}/`. Schemas/PromptPlan/adaptadores y el binding por construcción siguen en el media-plane. Ver `docs/superpowers/specs/2026-06-27-experimental-setup-config-design.md`.

**Execution path (single-host)**: `POST /api/runs` (`service/routers/runs.py`) → `RunManager` → `runtime/pipeline.py:execute_run()` → producer thread (read → rate-gate → normalize) + consumer thread (inference → postprocess → write), coupled via `MemoryTransportAdapter`. The model is loaded once at service startup (`EOVRT_MODEL_REF`), not per run. The `eovrt-media` CLI no longer exists.

**Execution path (two-node)**: `run-producer` → `runtime/two_node.py:run_node_a()` (ingesta + ZeroMQ REP server); `run-consumer` → `runtime/two_node.py:run_node_b()` (ZeroMQ REQ client + inference + artifacts). Transport: `NetworkTransportAdapter` (ZeroMQ REQ/REP, msgpack serialization, heartbeat PUSH/PULL dedicado).

**Key abstractions**:
- `BaseDetectorAdapter` (`models/base.py`) — plugin interface for inference; register new adapters in `models/__init__.py:create_adapter()`
- `BaseSource` (`sources/base.py`) — yields `VisualUnit` objects; implementations: `ImageFolderSource`, `VideoFileSource`, `RtspSource` (live RTSP with wall-clock timestamps and reconnect), `OakDSource` (OAK-D Pro PoE deferred, raises `NotImplementedError`)
- `RunContext` (`runtime/run_context.py`) — stateful execution context (run_id, unit counts, timing); owns the output directory
- `RunArtifactWriter` (`sinks/run_artifact_writer.py`) — persists to `runs/<run_id>/`: `detections.jsonl`, `metrics.jsonl`, `errors.jsonl`, `summary.json`, `previews/`

**Data contracts** (`contracts/`) — Pydantic models flow through the pipeline: `VisualUnit` → `RawDetection` → `Detection` → `DetectionEvent`/`MetricSample` for persistence.

**Error handling**: each pipeline stage catches independently; failures are logged to `errors.jsonl` and execution continues to the next unit.

**Metrics**: sub-stage latency tracked at microsecond granularity via `metrics/timers.py`; aggregated (p95, p99, FPS) in `metrics/collector.py`.

## Testing

`MockDetector` (`models/mock_detector.py`) enables full end-to-end pipeline tests without loading real model weights — use it for integration tests. Tests live in `tests/`; fixtures in `tests/conftest.py`.

## Out of scope

This pipeline does not implement: risk rules, alert generation, multi-object tracking (MOT), zones/geofences, control plane logic, UI, or message queues.
