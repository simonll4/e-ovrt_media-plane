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
        "prompts": {
          "set_inline": {"id": "demo", "classes": [{"id": "person", "phrasings": {"default": ["person"]}}]},
          "active_ids": ["person"]
        }
      }'
# GET  /api/runs/{run_id}            — estado/resumen (incluye bench_split/evaluated)
# WS   /api/runs/{run_id}/stream     — eventos en vivo (detecciones/métricas)
# POST /api/runs/{run_id}/stop       — detener la corrida activa
# POST /api/runs/{run_id}/evaluate   — evaluar un run BENCH terminado (AP@0.5/CR-01/mAP50)
# GET  /api/runs/{run_id}/evaluate   — releer eval_perception.json persistido (404 si no evaluado)

# Two-node topology (EBE distributed) — se sigue invocando en proceso, no vía CLI:
# runtime/two_node.py:run_node_a() / run_node_b(); ver tests/test_two_node.py.

# Utilidades standalone (ex-subcomandos CLI), invocables como módulos:
python -m eovrt_media.tools.evaluate --run runs/<run_id> [--bench-coco ...] [--person-gt ...]
python -m eovrt_media.tools.inspect_runs inspect runs/<run_id>
python -m eovrt_media.tools.inspect_runs compare runs/          # tabla comparativa
python -m eovrt_media.tools.debug_run --source bench-val [...]  # campaña de debug
# CAVEAT: la ruta de dos-nodos-local de debug_run (run_two_node_local) NO funciona
# post-eliminación-del-CLI (spawnea el `eovrt_media.cli` borrado); ahora falla con un
# RuntimeError explícito. Su reemplazo es infra/twonode/ (Fase 2, ya completada); la
# ruta local queda deshabilitada permanentemente, sin puente hacia el despliegue Docker.

# Test
make test                                       # pytest -q
pytest tests/test_pipeline_mock.py              # single module
pytest -xvs                                     # verbose, stop on first failure

# Lint
make lint                                       # ruff check src tests

# Docker (deploy standalone de este servicio; la plataforma completa vive en
# e-ovrt_experimental-setup/infra/platform/):
cd infra && EOVRT_MODEL_REF=mock docker compose up -d   # imagen: infra/docker/Dockerfile
```

## Architecture

Python pipeline for open-vocabulary object detection (OVD). All behavior is config-driven via YAML; no hardcoded paths or thresholds.

**Config catalogs (dos raíces)**: los **manifiestos de corrida** y los **prompt sets** viven en el repo hermano `e-ovrt_experimental-setup` (`experiments/` y `prompts/`). El media-plane conserva los **catálogos de capacidades** `configs/models/` y `configs/datasets/`. Un manifiesto compone por referencia: `model.ref`/`source.ref` → catálogo del plano (autodescubierto repo-relative; override `EOVRT_MEDIA_CATALOG_ROOT`); `prompts.ref` → `experimental-setup/prompts/<name>.yaml` (raíz del experimento, descubierta subiendo hasta el dir con `prompts/`). Inline fields override catalog values; resolución en `config/loader.py` (`find_plane_catalog_root` + `find_experiment_root`). Los tests usan `tests/fixtures/{runs,prompts}/`. Schemas/PromptPlan/adaptadores y el binding por construcción siguen en el media-plane. Ver `docs/superpowers/specs/2026-06-27-experimental-setup-config-design.md`.

**Execution path (single-host)**: `POST /api/runs` (`service/routers/runs.py`) → `RunManager` → `runtime/pipeline.py:execute_run()` → producer thread (read → rate-gate → normalize) + consumer thread (inference → postprocess → write), coupled via `MemoryTransportAdapter`. The model is loaded once at service startup (`EOVRT_MODEL_REF`), not per run. The `eovrt-media` CLI no longer exists.

**Execution path (two-node)**: invoked in-process (no CLI) — `runtime/two_node.py:run_node_a()` (ingesta + ZeroMQ REP server) and `run_node_b()` (ZeroMQ REQ client + inference + artifacts); the run config must set `topology.mode: two_node` (loader derives `transport.backend: network`). Transport: `NetworkTransportAdapter` (ZeroMQ REQ/REP, msgpack serialization, heartbeat PUSH/PULL dedicado). Docker packaging of the two-node split lives in `infra/twonode/` (Fase 2, see its README).

**Key abstractions**:
- `BaseDetectorAdapter` (`models/base.py`) — plugin interface for inference; register new adapters in `models/__init__.py:create_adapter()`
- `BaseSource` (`sources/base.py`) — yields `VisualUnit` objects; implementations: `ImageFolderSource`, `VideoFileSource`, `RtspSource` (live RTSP with wall-clock timestamps and reconnect), `OakDSource` (OAK-D Pro PoE deferred, raises `NotImplementedError`)
- `RunContext` (`runtime/run_context.py`) — stateful execution context (run_id, unit counts, timing); owns the output directory
- `RunArtifactWriter` (`sinks/run_artifact_writer.py`) — persists to `runs/<run_id>/`: `detections.jsonl`, `metrics.jsonl`, `errors.jsonl`, `summary.json`, `previews/`

**Bus media→control (ADR-003)**: apagado por default. Con `bus.enabled: true` en la run config —o una sección `"bus"` en el body de `POST /api/runs`— el `BusPublishingArtifactWriter` (`service/bus_writer.py`) decora el `RunArtifactWriter` y publica cada `DetectionEvent` **ya persistido** por un socket ZeroMQ XPUB (`transport/bus.py`), dentro de un envelope msgpack `bus.envelope.v1`, en el topic `media.detection.v1.<run_id>`; al cerrar el run emite `run.lifecycle.v1.<run_id>` con `{event: run_finished, status}`. El `payload` es **byte-idéntico a la línea de `detections.jsonl`** (invariante del test de paridad del control-plane). El bus nunca bloquea ni rompe la corrida: HWM finito, `NOBLOCK`, y **el JSONL es la fuente de verdad**. Un PUB/XPUB dropea en silencio al llenarse el HWM, así que el `seq` monótono del envelope (que se incrementa aunque el envío se descarte) es la única señal de pérdida — la detecta el consumidor. Ver `docs/operacion/37` del repo `docs`.

**Data contracts** (`contracts/`) — Pydantic models flow through the pipeline: `VisualUnit` → `RawDetection` → `Detection` → `DetectionEvent`/`MetricSample` for persistence.

**Error handling**: each pipeline stage catches independently; failures are logged to `errors.jsonl` and execution continues to the next unit.

**Metrics**: sub-stage latency tracked at microsecond granularity via `metrics/timers.py`; aggregated (p95, p99, FPS) in `metrics/collector.py`.

**Instrumentación de `t_capture→alert`** (spec 40 §5.2.4): `metrics.jsonl` trae, por `unit_id` —que es la clave de join con las alertas del control-plane—, `capture_monotonic_ns`, `capture_wallclock_ms` y `g2a_ms` (la compuesta captura → resultado algorítmico, que **cierra al terminar la inferencia**, antes del postproceso). El instante de captura se estampa con un `default_factory` en `VisualUnit`: se evalúa al construirlo, o sea al leer la unidad, y **`normalize_spatial` lo copia explícitamente** — si alguien borra ese copiado, el `NormalizedUnit` lo re-estampa en silencio y el G2A colapsa a cero (hay un test con un `sleep` que lo caza). `summary.json` declara `source_clock` (`wallclock` RTSP / `media` archivo de video / `none` imágenes: decide la aplicabilidad de la métrica aguas abajo) y el bloque `g2a` con percentiles, `warmup_units` excluidas y el presupuesto 50–250 ms. **En two-node `g2a_ms` es `null` por fila** y el bloque sale `not_interpretable / cross_node_monotonic_clock`: los relojes monotónicos de dos hosts no se restan. Ver `docs/operacion/39` del repo `docs`.

## Testing

`MockDetector` (`models/mock_detector.py`) enables full end-to-end pipeline tests without loading real model weights — use it for integration tests. Tests live in `tests/`; fixtures in `tests/conftest.py`.

## Out of scope

This pipeline does not implement: risk rules, alert generation, multi-object tracking (MOT), zones/geofences, control plane logic, UI, or message queues.
