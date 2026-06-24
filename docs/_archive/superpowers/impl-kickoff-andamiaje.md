# Kickoff: implementación del andamiaje de despliegue

Lee primero el spec completo:
`docs/superpowers/specs/2026-06-21-plano-medios-topologia-despliegue-andamiaje-design.md`

Lee también (contexto de diseño):
`docs/contexto/topologias-despliegue-dbe-ebe.md`

---

## Qué se implementa en esta sesión

**Escenario A únicamente: un host + DBE.** El andamiaje deja listas las 4 combinaciones
(DBE/EBE × un host/dos hosts), pero ahora solo se implementa el camino prioritario.

Las cuatro piezas centrales a construir:

### 1. Contrato `NormalizedUnit` + `ModelInputSpec`
- Nuevo contrato Pydantic en `contracts/` que viaja por el canal (ver §5 del spec).
- Campos: metadata de `VisualUnit` + `payload` (ndarray) + `payload_format` + `target_size` + `transform` (para reproyectar cajas).
- `ModelInputSpec` en cada adapter: declara `target_size`, `resize_mode`, `mean`, `std`, `dtype`.

### 2. Etapa `Normalizer` (productor)
- Nueva etapa en `preprocessing/` (o `stages/normalizer.py`).
- Hace: decode → asegurar RGB → resize/letterbox según `ModelInputSpec` → produce `NormalizedUnit`.
- Hoy esto está implícito en cada `adapter.infer(pil_image)`. Se extrae como etapa propia.
- **Verificar paridad numérica** con el preprocesamiento actual de GDINO y YOLOE (test golden).

### 3. `TransportAdapter` + backend `memory` + políticas de rate control
- Interfaz abstracta `TransportAdapter` con `offer(unit)` / `request()` / `close()` en `transport/`.
- Backend `MemoryTransportAdapter`: cola acotada (`queue.Queue`) con disciplina por política.
  - `deterministic`: `offer` bloquea si la cola está llena (backpressure). Parámetros: `stride`, `max_queue_size`.
  - `bounded_freshness`: `offer` hace head-drop del más viejo si llena + `max_staleness_ms`. Parámetros: `buffer_size`, `max_staleness_ms`.
- Backends `ipc` y `network` declarados (factory → `NotImplementedError` con mensaje claro).
- `RateGate` (aplica `stride`, solo `deterministic`) como paso previo al canal.

### 4. Refactor del pipeline + config schema
- `runtime/pipeline.py`: pasar de loop síncrono único a **hilo productor** (ingesta→RateGate→Normalizer→channel.offer) + **consumidor en main** (channel.request→inference→postprocess→write).
- Apagado limpio: centinela `END`; el productor lo emite al agotar la fuente.
- Nuevas secciones de config en `config/schemas.py`: `rate_control`, `transport`, `topology`.
- Derivación: `source.type → source.kind → rate_control.policy default` y `topology.mode → transport.backend default`.
- Migración dura de `sampling` (→ error si presente, con mensaje de mapeo).
- Gating: config puede expresar EBE/two_node/network, runtime falla rápido con mensaje claro.
- `effective_config.yaml` materializa los defaults derivados.
- Catálogos `configs/datasets/*.yaml` ganan: `dataset_id`, `view`, `split`, `vocabulary`.

---

## Qué NO tocar (solo declarar)

| Pieza | Lo que existe en código |
|---|---|
| Fuente `live` (cámara/RTSP) | `LiveSource(BaseSource)` abstracta, factory → `NotImplementedError` |
| Backend `ipc` | `IpcTransportAdapter` registrado, no implementado |
| Backend `network` (ZMQ) | `NetworkTransportAdapter` registrado, mensajes `REQUEST`/`RESPONSE`/`HEARTBEAT` como contratos; no implementado |
| `topology.mode = two_node` | Config válida, `run` falla rápido |
| `payload_format: fp16` | Enum válido, cast no implementado |

**Criterio de aceptación de extensibilidad**: implementar cualquier pieza diferida debe ser solo
rellenar detrás de una interfaz que ya existe, sin modificar contratos ni los roles
productor/consumidor.

---

## Trazabilidad y métricas (a completar en el mismo paso)

- `summary.json` gana bloque `run_descriptor` (scenario, topology, transport, rate_control, source_kind, model, device, code_version).
- `run_provenance.json` nuevo (dataset_id, view, split, vocabulary, source_fingerprint = hash de archivos fuente).
- Métricas nuevas en `summary.json`: `p99_latency_ms`, desglose por etapa normalize/write, `units_dropped`, `backpressure_wait_ms`, `max_staleness_observed_ms`.
- `schema_version` en `summary.json` y en registros de `metrics.jsonl`.
- CLI `inspect-run runs/<id>` (implementar).
- Auto-naming de run_id: `run_{ts}_{scenario}_{model}_{policy}` si `run.id` no se fija.

---

## Estado actual del código (lo que hay hoy)

```
src/eovrt_media/
  cli.py                      # run, validate-config, download-models (inspect-run falta)
  config/
    schemas.py                # RunConfig con sampling (a migrar), sin rate_control/transport/topology
    loader.py                 # resolución de refs; agregar derivación de defaults
  runtime/
    pipeline.py               # loop síncrono por unidad — refactor central
    run_context.py            # run_id, run_dir, timing
  sources/
    base.py                   # BaseSource → yields VisualUnit
    image_folder_source.py
    video_file_source.py
  preprocessing/
    image_loader.py           # load_image(unit) → PIL Image — reemplazar con Normalizer
  models/
    base.py                   # BaseDetectorAdapter.infer(pil_image, prompts) → RawDetection[]
    grounding_dino_adapter.py
    yoloe_adapter.py
    mock_detector.py          # usar en todos los tests
  postprocessing/
    detection_normalizer.py   # RawDetection[] → Detection[] (usa coords píxeles)
  sinks/
    run_artifact_writer.py    # detections.jsonl, metrics.jsonl, summary.json, etc.
  contracts/
    visual_unit.py            # VisualUnit (origen)
    detection.py              # RawDetection, Detection
    events.py                 # DetectionEvent, RunSummary
    metrics.py                # MetricSample
  metrics/
    timers.py
    collector.py
```

---

## Tests existentes relevantes

```bash
make test               # pytest -q
pytest -xvs             # verbose, para en primer fallo
pytest tests/test_pipeline_mock.py  # pipeline end-to-end con MockDetector
```

**Tests nuevos que deben existir al terminar**:
- Reproducibilidad de `deterministic`: misma config dos veces → `detections.jsonl` idéntico.
- Políticas: `bounded_freshness` hace head-drop bajo carga; `units_dropped` se cuenta bien.
- Concurrencia: apagado limpio vía `END`; aislamiento de errores por etapa.
- Normalizer: paridad numérica con preprocesamiento actual (golden test GDINO + YOLOE).
- Config: derivación, errores cruzados, gating de features declaradas.
- Trazabilidad: `source_fingerprint` estable, `run_descriptor` presente.
- `TransportAdapter` agnóstico de backend (escrita para que el futuro backend `network` corra los mismos tests).

---

## Regla de git

**Nunca agregar `Co-Authored-By:` a los commits.** Sin ninguna atribución de co-autor.

---

## Setup

```bash
cd e-ovrt_media-plane
source .venv/bin/activate   # o: python3.11 -m venv .venv && pip install -e ".[dev]"
make test                   # verificar estado base antes de tocar nada
```
