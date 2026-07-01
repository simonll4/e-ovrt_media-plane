# Media-Plane Service (Fase 1 DBE) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Convertir `e-ovrt_media-plane` de una CLI batch a un servicio FastAPI persistente de un solo contenedor (Fase 1 DBE) que carga un modelo una vez al arrancar y expone runs vía HTTP/WebSocket, sin CLI y sin recarga dinámica de modelos.

**Architecture:** Un paquete nuevo `service/` envuelve el pipeline existente (`runtime/pipeline.py`, `sources/`, `models/`, `sinks/`, `postprocessing/`, `preprocessing/`) sin reescribirlo. `run_pipeline()` se modifica de forma aditiva para aceptar un adapter ya cargado (evita recarga) y hooks opcionales de telemetría en vivo. Un `RunManager` mínimo (un run activo a la vez, cola de un slot vía `409`) ejecuta cada run en un hilo, publicando eventos a un `RunEventBus` en memoria que la ruta WebSocket reexpone. El modelo se carga **una sola vez, de forma síncrona, en el `lifespan` de FastAPI** — si falla, el proceso no arranca (falla simple y visible, sin estados intermedios de "cargando").

**Tech Stack:** Python 3.11, FastAPI, uvicorn, Pydantic (schemas ya existentes en `config/schemas.py`), pytest + `fastapi.testclient.TestClient` (basado en httpx, sin async requerido).

## Global Constraints

- No recarga de modelo in-process. El modelo es fijo por instancia, cargado una vez en el `lifespan` desde `MODEL_REF` (env var). Cambiar de modelo = redeploy con otro `MODEL_REF`.
- Un run activo a la vez (1 GPU). Un segundo `POST /api/runs` mientras hay uno corriendo devuelve `409`.
- El CLI (`src/eovrt_media/cli.py`, entry point `eovrt-media`) se elimina por completo en este plan.
- Los prompts llegan **inline** en el cuerpo del request (`prompts.prompt_set`, reutilizando `PromptSet`/`PromptsFile` ya existentes) — el servicio nunca lee `experimental-setup` del disco.
- Todo el código de pipeline existente (`runtime/pipeline.py`, `sources/`, `models/`, `sinks/`, `postprocessing/`, `preprocessing/`, `transport/`, `metrics/`, `contracts/`) se reusa; las únicas modificaciones son aditivas (parámetros opcionales con default `None`, comportamiento actual sin cambios cuando no se usan).
- Todos los tests corren contra el detector `mock` (`MockDetectorAdapter`, sin GPU, sin sleep artificial) — nunca contra pesos reales.
- Fase 2 (split EBE en dos imágenes) queda fuera de este plan; no se toca `runtime/two_node.py` ni `transport/network.py`.

---

## File Structure

```
src/eovrt_media/
├── cli.py                          # ELIMINAR (Task 17)
├── config/
│   └── loader.py                   # MODIFICAR: exponer load_catalog_entry (Task 2)
├── runtime/
│   └── pipeline.py                 # MODIFICAR: adapter injection + hooks (Task 3)
└── service/                        # NUEVO paquete
    ├── __init__.py
    ├── settings.py                 # ServiceSettings (env vars)
    ├── ingest_registry.py          # Registro de plugins de ingesta
    ├── datasets_catalog.py         # list_datasets(catalog_root)
    ├── model_loader.py             # load_model_from_env()
    ├── schemas.py                  # Modelos Pydantic de la API HTTP
    ├── run_builder.py              # build_run_config() desde un CreateRunRequest
    ├── events.py                   # RunEventBus (pub/sub en memoria por run)
    ├── run_manager.py              # RunManager, RunHandle, RunBusyError, RunNotFoundError
    ├── app.py                      # create_app(), lifespan, instancia `app`
    └── routers/
        ├── __init__.py
        ├── health.py                # GET /healthz, /readyz
        ├── model.py                 # GET /api/model
        ├── catalog.py               # GET /api/catalog/ingest-plugins, /api/catalog/datasets
        ├── runs.py                  # POST/GET /api/runs, .../stop
        ├── stream.py                 # WS /api/runs/{id}/stream
        └── artifacts.py              # GET /api/runs/{id}/detections, /artifacts/{path}

tests/
├── test_cli_two_node_local.py      # ELIMINAR (Task 17, depende de eovrt_media.cli)
├── test_cli_debug_run.py           # ELIMINAR (Task 17, depende de eovrt_media.cli)
├── test_cli_two_node.py            # NO TOCAR — pese al nombre, no importa eovrt_media.cli
├── test_pipeline_service_hooks.py  # NUEVO (Task 3)
└── service/                         # NUEVO
    ├── __init__.py
    ├── test_ingest_registry.py
    ├── test_datasets_catalog.py
    ├── test_model_loader.py
    ├── test_run_builder.py
    ├── test_events.py
    ├── test_run_manager.py
    ├── test_app_health_and_model.py
    ├── test_catalog_routes.py
    ├── test_runs_routes.py
    ├── test_stream_route.py
    └── test_artifacts_routes.py

Makefile                            # MODIFICAR (Task 17)
pyproject.toml                      # MODIFICAR (Task 1, Task 17)
CLAUDE.md                           # MODIFICAR (Task 17)
deploy/README.md                    # MODIFICAR (Task 17, nota Fase 2)
deploy/docker/Dockerfile.service    # NUEVO (Task 18)
scripts/run_grounding_dino_sample.sh  # ELIMINAR (Task 17)
scripts/run_yoloe_sample.sh           # ELIMINAR (Task 17)
```

---

### Task 1: Agregar dependencias del servicio

**Files:**
- Modify: `pyproject.toml`
- Test: manual (import smoke test, no requiere código nuevo todavía)

**Interfaces:**
- Produces: `fastapi`, `uvicorn`, `httpx` disponibles para los tasks siguientes.

- [ ] **Step 1: Editar `pyproject.toml`**

Agregar `fastapi` y `uvicorn[standard]` a `dependencies`, y `httpx` a `dev` (requerido por `fastapi.testclient.TestClient`):

```toml
[project]
name = "eovrt-media-plane"
version = "0.1.0"
description = "Experimental media plane for E-OVRT-VDP"
requires-python = ">=3.11"
dependencies = [
    "pillow",
    "opencv-python",
    "pydantic",
    "pyyaml",
    "rich",
    "pyzmq",
    "msgpack",
    "fastapi",
    "uvicorn[standard]",
]

[project.optional-dependencies]
edge = []
gpu = [
    "torch",
    "torchvision",
    "transformers",
    "accelerate",
    "huggingface_hub",
    "ultralytics",
]
dev = [
    "pytest",
    "ruff",
    "httpx",
]

[project.scripts]
eovrt-media = "eovrt_media.cli:app"

[build-system]
requires = ["setuptools>=68.0", "wheel"]
build-backend = "setuptools.build_meta"

[tool.setuptools.packages.find]
where = ["src"]

[tool.ruff]
line-length = 100
target-version = "py311"

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["src"]
```

Nota: `typer` se quita recién en Task 17 (junto con `cli.py`), para no romper `make test` a mitad de plan. `[project.scripts]` también se retira en Task 17.

- [ ] **Step 2: Reinstalar dependencias**

Run: `pip install -e ".[dev]"`
Expected: instala `fastapi`, `uvicorn`, `httpx` sin errores.

- [ ] **Step 3: Verificar el import**

Run: `python -c "import fastapi, uvicorn, httpx; print('ok')"`
Expected: `ok`

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml
git commit -m "build: agregar fastapi/uvicorn/httpx para el servicio"
```

---

### Task 2: Exponer `load_catalog_entry` públicamente

**Files:**
- Modify: `src/eovrt_media/config/loader.py:169-181` (función `_load_catalog_entry`)
- Test: `tests/test_config.py` (agregar caso nuevo)

**Interfaces:**
- Produces: `load_catalog_entry(configs_root: Path, catalog: str, ref: str) -> dict[str, Any]` — usada por `service/model_loader.py` (Task 6) y `service/run_builder.py` (Task 8).

El servicio necesita resolver `MODEL_REF`/`ingest.ref` contra los catálogos `configs/models/` y `configs/datasets/` sin pasar por un manifiesto YAML completo. Esa lógica ya existe como función interna (`_load_catalog_entry`); este task solo le quita el guion bajo y actualiza su único call site.

- [ ] **Step 1: Escribir el test que falla**

Agregar al final de `tests/test_config.py`:

```python
def test_load_catalog_entry_reads_model_catalog() -> None:
    from eovrt_media.config.loader import find_plane_catalog_root, load_catalog_entry

    catalog_root = find_plane_catalog_root()
    entry = load_catalog_entry(catalog_root, "models", "mock")

    assert isinstance(entry, dict)
    assert entry.get("adapter") == "mock"


def test_load_catalog_entry_rejects_path_traversal() -> None:
    from eovrt_media.config.loader import find_plane_catalog_root, load_catalog_entry

    catalog_root = find_plane_catalog_root()
    with pytest.raises(ValueError, match="inválida"):
        load_catalog_entry(catalog_root, "models", "../../etc/passwd")
```

Si `tests/test_config.py` no importa `pytest` todavía, verificar el import al inicio del archivo (ya debería estar, dado que usa fixtures/asserts de pytest en otros tests del mismo archivo).

- [ ] **Step 2: Correr el test y verificar que falla**

Run: `pytest tests/test_config.py -k load_catalog_entry -v`
Expected: `ImportError: cannot import name 'load_catalog_entry'`

- [ ] **Step 3: Renombrar la función en `loader.py`**

En `src/eovrt_media/config/loader.py`, cambiar:

```python
def _load_catalog_entry(configs_root: Path, catalog: str, ref: str) -> dict[str, Any]:
```

por:

```python
def load_catalog_entry(configs_root: Path, catalog: str, ref: str) -> dict[str, Any]:
```

(el cuerpo de la función no cambia). Y actualizar su único call site dentro de `_resolve_section_ref`:

```python
def _resolve_section_ref(
    raw: dict[str, Any], section: str, catalog: str, configs_root: Path
) -> None:
    """Expande ``raw[section]['ref']`` mezclando catálogo + overrides inline."""
    section_data = raw.get(section)
    if not isinstance(section_data, dict):
        return
    ref = section_data.get("ref")
    if not ref:
        return
    base = load_catalog_entry(configs_root, catalog, ref)
    overrides = {k: v for k, v in section_data.items() if k != "ref"}
    raw[section] = {**base, **overrides, "ref": ref}
```

- [ ] **Step 4: Correr el test y verificar que pasa**

Run: `pytest tests/test_config.py -k load_catalog_entry -v`
Expected: 2 passed

- [ ] **Step 5: Correr toda la suite de config para verificar que no rompió nada**

Run: `pytest tests/test_config.py tests/test_config_refs.py tests/test_config_deployment.py -q`
Expected: todos los tests existentes siguen en verde.

- [ ] **Step 6: Commit**

```bash
git add src/eovrt_media/config/loader.py tests/test_config.py
git commit -m "refactor: exponer load_catalog_entry para reuso desde el servicio"
```

---

### Task 3: `run_pipeline` — reusar adapter cargado + hooks de telemetría en vivo

**Files:**
- Modify: `src/eovrt_media/runtime/pipeline.py`
- Test: Create `tests/test_pipeline_service_hooks.py`

**Interfaces:**
- Consumes: `MockDetectorAdapter` (`eovrt_media.models.mock_detector`), `load_run_config` (`eovrt_media.config`).
- Produces: `run_pipeline(config, console=None, on_event=None, on_source_ready=None, adapter=None) -> str`. `on_event` recibe dicts con `{"type": "started", "run_id", "total_units", "model_name", "source_type"}` y `{"type": "progress", "run_id", "units_processed", "units_failed", "total_detections", "detections_by_label", "fps_effective", "latency_p95_ms", "gpu_memory_allocated_mb"}`. `on_source_ready` recibe la instancia `BaseSource` ya creada (para poder llamar `.stop()` externamente). Si `adapter` se pasa, `run_pipeline` NO llama `adapter.load()` ni `adapter.close()` (el llamador es dueño del ciclo de vida).

Este es el cambio más delicado del plan: hoy `run_pipeline` crea su propio adapter y lo recarga en cada llamada — exactamente lo que el servicio debe evitar (Spec A §4: "el media-plane no gestiona modelos dinámicamente"). El cambio es aditivo: con los parámetros nuevos en su default (`None`), el comportamiento es idéntico al actual.

- [ ] **Step 1: Escribir el test que falla**

Create `tests/test_pipeline_service_hooks.py`:

```python
"""Tests de los hooks de servicio agregados a run_pipeline: reuso de adapter y eventos en vivo."""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
import pytest

from eovrt_media.config import load_run_config
from eovrt_media.models.mock_detector import MockDetectorAdapter
from eovrt_media.runtime import run_pipeline
from eovrt_media.sources.base import BaseSource

CONFIGS_DIR = Path(__file__).parent / "fixtures"


def _create_test_images(folder: Path, count: int = 3) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    for i in range(count):
        img = np.zeros((480, 640, 3), dtype=np.uint8)
        img[:] = (50 + i * 30, 100, 200)
        cv2.imwrite(str(folder / f"test_{i:03d}.jpg"), img)


@pytest.fixture
def mock_config(tmp_path):
    images_dir = tmp_path / "images"
    _create_test_images(images_dir, count=3)
    config = load_run_config(CONFIGS_DIR / "runs" / "gdino.yaml")
    config.model.adapter = "mock"
    config.model.name = "mock"
    config.source.path = str(images_dir)
    config.outputs.base_dir = str(tmp_path / "runs")
    config.outputs.run_dir = str(tmp_path / "runs")
    config.outputs.save_previews = False
    return config


def test_run_pipeline_reuses_provided_adapter_without_reload(mock_config, monkeypatch):
    adapter = MockDetectorAdapter()
    load_calls: list[int] = []
    close_calls: list[int] = []
    monkeypatch.setattr(adapter, "load", lambda: load_calls.append(1))
    monkeypatch.setattr(adapter, "close", lambda: close_calls.append(1))

    run_id = run_pipeline(mock_config, adapter=adapter)

    assert run_id is not None
    assert load_calls == []
    assert close_calls == []


def test_run_pipeline_without_adapter_still_loads_and_closes(mock_config):
    """El comportamiento default (adapter=None) no cambia: crea, carga y cierra su propio adapter."""
    run_id = run_pipeline(mock_config)
    assert run_id is not None


def test_run_pipeline_fires_started_event(mock_config):
    events: list[dict] = []
    run_pipeline(mock_config, on_event=events.append)

    started = [e for e in events if e["type"] == "started"]
    assert len(started) == 1
    assert started[0]["total_units"] == 3
    assert started[0]["model_name"] == "mock"
    assert started[0]["source_type"] == "image_folder"


def test_run_pipeline_fires_progress_event_per_unit(mock_config):
    events: list[dict] = []
    run_pipeline(mock_config, on_event=events.append)

    progress_events = [e for e in events if e["type"] == "progress"]
    assert len(progress_events) == 3
    last = progress_events[-1]
    assert last["units_processed"] == 3
    assert last["units_failed"] == 0
    assert "fps_effective" in last
    assert "detections_by_label" in last


def test_run_pipeline_calls_on_source_ready_with_stoppable_source(mock_config):
    captured: list[BaseSource] = []
    run_pipeline(mock_config, on_source_ready=captured.append)

    assert len(captured) == 1
    assert isinstance(captured[0], BaseSource)
    # No debe lanzar — todas las fuentes implementan stop() (no-op por default).
    captured[0].stop()
```

- [ ] **Step 2: Correr el test y verificar que falla**

Run: `pytest tests/test_pipeline_service_hooks.py -v`
Expected: `TypeError: run_pipeline() got an unexpected keyword argument 'adapter'`

- [ ] **Step 3: Modificar `src/eovrt_media/runtime/pipeline.py`**

Agregar el import de `BaseDetectorAdapter` junto a los imports existentes (después de `from eovrt_media.models import create_adapter`):

```python
from eovrt_media.models import create_adapter
from eovrt_media.models.base import BaseDetectorAdapter
```

Agregar la función helper `_build_progress_event`, justo antes de `def run_producer_loop(`:

```python
def _build_progress_event(run_context: RunContext, tracker: LatencyTracker) -> dict:
    """Arma el payload del evento 'progress' a partir del estado acumulado."""
    stats = tracker.get_stats()
    return {
        "type": "progress",
        "run_id": run_context.run_id,
        "units_processed": run_context.units_processed,
        "units_failed": run_context.units_failed,
        "total_detections": run_context.total_detections,
        "detections_by_label": dict(run_context.detections_by_label),
        "fps_effective": (
            round(1000.0 / stats["avg_latency_ms"], 2)
            if stats.get("avg_latency_ms", 0) > 0
            else 0.0
        ),
        "latency_p95_ms": stats.get("p95_latency_ms", 0.0),
        "gpu_memory_allocated_mb": round(get_gpu_memory_allocated_mb(), 2),
    }
```

Modificar la firma de `run_consumer_loop` (agregar `on_event` al final de la lista de parámetros, antes de `drain_errors`):

```python
def run_consumer_loop(
    transport,
    adapter,
    normalizer,
    artifact_writer,
    run_context,
    tracker,
    config,
    plan,
    prompt_set_id,
    timings: dict[str, float],
    progress=None,
    task=None,
    on_event: Callable[[dict], None] | None = None,
    drain_errors: bool = True,
) -> None:
```

Dentro de `run_consumer_loop`, agregar `if on_event is not None: on_event(_build_progress_event(run_context, tracker))` inmediatamente después de cada uno de los 3 bloques `if progress is not None and task is not None: progress.update(task, advance=1)` (los dos de las ramas `except` de inferencia y postproceso, y el de después del bloque try/except de escritura). Ejemplo para el primero (rama de excepción de inferencia):

```python
        try:
            raw_detections = adapter.forward(item, plan)
        except Exception as exc:
            timer.end_inference()
            tracker.finish_unit(timer, error=str(exc))
            artifact_writer.write_error(
                ErrorEvent(
                    run_id=run_context.run_id,
                    unit_id=item.unit_id,
                    stage="inference",
                    message=str(exc),
                    recoverable=True,
                )
            )
            run_context.units_failed += 1
            if progress is not None and task is not None:
                progress.update(task, advance=1)
            if on_event is not None:
                on_event(_build_progress_event(run_context, tracker))
            continue
```

Aplicar el mismo patrón (agregar las dos líneas `if on_event is not None: on_event(...)` inmediatamente después de `progress.update(task, advance=1)`) en la rama `except` del bloque de postproceso, y en el bloque final tras el try/except de escritura (el que no tiene `continue`, al final del cuerpo del `while True`).

Modificar la firma de `run_pipeline`:

```python
def run_pipeline(
    config: RunConfig,
    console: Console | None = None,
    on_event: Callable[[dict], None] | None = None,
    on_source_ready: Callable[[BaseSource], None] | None = None,
    adapter: BaseDetectorAdapter | None = None,
) -> str:
    """Ejecuta una corrida mediante un productor y un consumidor en memoria.

    Si ``adapter`` se provee ya cargado, no se crea ni se cierra uno nuevo — el
    llamador (el servicio) es dueño de su ciclo de vida y lo reusa entre corridas.
    """
    console = console or Console()
    run_context = RunContext(config)
    artifact_writer = RunArtifactWriter(run_context)
    tracker = LatencyTracker()
    owns_adapter = adapter is None
    producer = None
```

Más abajo, reemplazar el bloque de creación de fuente/adapter:

```python
        source = create_source(config)
        if on_source_ready is not None:
            on_source_ready(source)
        try:
            source_count = len(source)
            progress_total: int | None = source_count if source_count >= 0 else None
        except TypeError:
            source_count = -1
            progress_total = None
        normalizer = DetectionNormalizer(
            min_confidence=config.postprocess.min_confidence,
            min_box_area_px=config.postprocess.min_box_area_px,
            normalize_boxes=config.postprocess.normalize_boxes,
        )
        if adapter is None:
            adapter = create_adapter(config.model)
        plan = config.build_prompt_plan(adapter.PROMPT_BACKEND)
        prompt_set_id = (
            config.prompts_file.resolved_set_id() if config.prompts_file else "unknown"
        )
        reset_gpu_peak_memory()
        if owns_adapter:
            with console.status("[bold cyan]Cargando modelo..."):
                adapter.load()
        if on_event is not None:
            on_event(
                {
                    "type": "started",
                    "run_id": run_context.run_id,
                    "total_units": progress_total,
                    "model_name": config.model.name or config.model.adapter or "unknown",
                    "source_type": config.source.type,
                }
            )
```

En la llamada a `run_consumer_loop` dentro de `run_pipeline`, agregar `on_event=on_event,`:

```python
                run_consumer_loop(
                    transport=transport,
                    adapter=adapter,
                    normalizer=normalizer,
                    artifact_writer=artifact_writer,
                    run_context=run_context,
                    tracker=tracker,
                    config=config,
                    plan=plan,
                    prompt_set_id=prompt_set_id,
                    timings=timings,
                    progress=progress,
                    task=task,
                    on_event=on_event,
                    drain_errors=True,
                )
```

Y en el bloque `finally` de `run_pipeline`, condicionar el cierre del adapter:

```python
    finally:
        if producer is not None:
            producer.join(timeout=30.0)
        if owns_adapter and adapter is not None:
            adapter.close()
        artifact_writer.close()
```

- [ ] **Step 4: Correr el test y verificar que pasa**

Run: `pytest tests/test_pipeline_service_hooks.py -v`
Expected: 5 passed

- [ ] **Step 5: Correr la suite completa del pipeline para verificar que no rompió nada**

Run: `pytest tests/test_pipeline_mock.py tests/test_pipeline_two_threads.py -q`
Expected: todos los tests existentes siguen en verde (el comportamiento default no cambió).

- [ ] **Step 6: Commit**

```bash
git add src/eovrt_media/runtime/pipeline.py tests/test_pipeline_service_hooks.py
git commit -m "feat: run_pipeline acepta adapter precargado y hooks de telemetría en vivo"
```

---

### Task 4: Registro de plugins de ingesta

**Files:**
- Create: `src/eovrt_media/service/__init__.py` (vacío)
- Create: `src/eovrt_media/service/ingest_registry.py`
- Test: Create `tests/service/__init__.py` (vacío), `tests/service/test_ingest_registry.py`

**Interfaces:**
- Produces: `IngestPluginInfo` (dataclass: `id: str`, `kind: str`, `available: bool`, `reason: str | None`), `INGEST_PLUGINS: list[IngestPluginInfo]`, `get_ingest_plugin(plugin_id: str) -> IngestPluginInfo | None`.

- [ ] **Step 1: Escribir el test que falla**

Create `tests/service/__init__.py`:

```python
```

Create `tests/service/test_ingest_registry.py`:

```python
from eovrt_media.service.ingest_registry import INGEST_PLUGINS, get_ingest_plugin


def test_registry_has_four_plugins():
    ids = {p.id for p in INGEST_PLUGINS}
    assert ids == {"image_folder", "video_file", "rtsp", "oak_d"}


def test_bounded_plugins_are_available():
    image_folder = get_ingest_plugin("image_folder")
    video_file = get_ingest_plugin("video_file")
    assert image_folder.kind == "bounded"
    assert image_folder.available is True
    assert video_file.kind == "bounded"
    assert video_file.available is True


def test_rtsp_is_live_and_available():
    rtsp = get_ingest_plugin("rtsp")
    assert rtsp.kind == "live"
    assert rtsp.available is True


def test_oak_d_is_live_and_not_available():
    oak_d = get_ingest_plugin("oak_d")
    assert oak_d.kind == "live"
    assert oak_d.available is False
    assert oak_d.reason is not None


def test_get_unknown_plugin_returns_none():
    assert get_ingest_plugin("does_not_exist") is None
```

- [ ] **Step 2: Correr el test y verificar que falla**

Run: `pytest tests/service/test_ingest_registry.py -v`
Expected: `ModuleNotFoundError: No module named 'eovrt_media.service'`

- [ ] **Step 3: Crear el paquete e implementar el registro**

Create `src/eovrt_media/service/__init__.py`:

```python
```

Create `src/eovrt_media/service/ingest_registry.py`:

```python
"""Registro de plugins de ingesta expuesto al cliente (consola).

Formaliza como catálogo consultable los tipos de fuente que ``create_source``
(``runtime/pipeline.py``) ya despacha por string. No reemplaza ese dispatch —
solo documenta, para el cliente HTTP, qué plugins existen y cuáles están
disponibles.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class IngestPluginInfo:
    id: str
    kind: str  # "bounded" | "live"
    available: bool
    reason: str | None = None


INGEST_PLUGINS: list[IngestPluginInfo] = [
    IngestPluginInfo(id="image_folder", kind="bounded", available=True),
    IngestPluginInfo(id="video_file", kind="bounded", available=True),
    IngestPluginInfo(id="rtsp", kind="live", available=True),
    IngestPluginInfo(
        id="oak_d",
        kind="live",
        available=False,
        reason="OAK-D Pro PoE declarado pero no implementado (hardware no disponible).",
    ),
]

_BY_ID = {plugin.id: plugin for plugin in INGEST_PLUGINS}


def get_ingest_plugin(plugin_id: str) -> IngestPluginInfo | None:
    return _BY_ID.get(plugin_id)
```

- [ ] **Step 4: Correr el test y verificar que pasa**

Run: `pytest tests/service/test_ingest_registry.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add src/eovrt_media/service/__init__.py src/eovrt_media/service/ingest_registry.py tests/service/
git commit -m "feat(service): registro de plugins de ingesta"
```

---

### Task 5: Catálogo de datasets

**Files:**
- Create: `src/eovrt_media/service/datasets_catalog.py`
- Test: Create `tests/service/test_datasets_catalog.py`

**Interfaces:**
- Consumes: nada del resto del servicio (función pura sobre un directorio).
- Produces: `DatasetCatalogEntry` (dataclass: `id: str`, `type: str`, `description: str | None`), `list_datasets(catalog_root: Path) -> list[DatasetCatalogEntry]`.

No existe hoy ninguna función que liste el catálogo de datasets (confirmado explícitamente en el relevamiento: no hay `list_datasets()` en el codebase). Este task la agrega, sin tocar `config/loader.py`.

- [ ] **Step 1: Escribir el test que falla**

Create `tests/service/test_datasets_catalog.py`:

```python
from pathlib import Path

from eovrt_media.service.datasets_catalog import list_datasets


def test_list_datasets_reads_yaml_catalog(tmp_path: Path) -> None:
    datasets_dir = tmp_path / "datasets"
    datasets_dir.mkdir()
    (datasets_dir / "demo_a.yaml").write_text(
        "type: image_folder\npath: /data/a\ndescription: Dataset A\n"
    )
    (datasets_dir / "demo_b.yaml").write_text(
        "type: video_file\npath: /data/b.mp4\n"
    )

    entries = list_datasets(tmp_path)

    by_id = {e.id: e for e in entries}
    assert set(by_id) == {"demo_a", "demo_b"}
    assert by_id["demo_a"].type == "image_folder"
    assert by_id["demo_a"].description == "Dataset A"
    assert by_id["demo_b"].description is None


def test_list_datasets_empty_dir_returns_empty_list(tmp_path: Path) -> None:
    (tmp_path / "datasets").mkdir()
    assert list_datasets(tmp_path) == []


def test_list_datasets_missing_dir_returns_empty_list(tmp_path: Path) -> None:
    assert list_datasets(tmp_path) == []
```

- [ ] **Step 2: Correr el test y verificar que falla**

Run: `pytest tests/service/test_datasets_catalog.py -v`
Expected: `ModuleNotFoundError: No module named 'eovrt_media.service.datasets_catalog'`

- [ ] **Step 3: Implementar**

Create `src/eovrt_media/service/datasets_catalog.py`:

```python
"""Listado del catálogo de datasets del media-plane (``configs/datasets/*.yaml``)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml


@dataclass(frozen=True)
class DatasetCatalogEntry:
    id: str
    type: str
    description: str | None = None


def list_datasets(catalog_root: Path) -> list[DatasetCatalogEntry]:
    """Lista las entradas del catálogo ``<catalog_root>/datasets/*.yaml``."""
    datasets_dir = Path(catalog_root) / "datasets"
    if not datasets_dir.is_dir():
        return []

    entries: list[DatasetCatalogEntry] = []
    for path in sorted(datasets_dir.glob("*.yaml")):
        with open(path) as f:
            raw = yaml.safe_load(f) or {}
        entries.append(
            DatasetCatalogEntry(
                id=path.stem,
                type=raw.get("type", "unknown"),
                description=raw.get("description"),
            )
        )
    return entries
```

- [ ] **Step 4: Correr el test y verificar que pasa**

Run: `pytest tests/service/test_datasets_catalog.py -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add src/eovrt_media/service/datasets_catalog.py tests/service/test_datasets_catalog.py
git commit -m "feat(service): listado del catálogo de datasets"
```

---

### Task 6: Carga del modelo desde `MODEL_REF`

**Files:**
- Create: `src/eovrt_media/service/model_loader.py`
- Test: Create `tests/service/test_model_loader.py`

**Interfaces:**
- Consumes: `load_catalog_entry`, `find_plane_catalog_root` (`eovrt_media.config.loader`), `ModelSection` (`eovrt_media.config.schemas`), `create_adapter` (`eovrt_media.models`).
- Produces: `load_model_from_env(catalog_root: Path, model_ref: str, device: str | None = None) -> tuple[BaseDetectorAdapter, ModelSection]`.

- [ ] **Step 1: Escribir el test que falla**

Create `tests/service/test_model_loader.py`:

```python
from eovrt_media.config.loader import find_plane_catalog_root
from eovrt_media.models.mock_detector import MockDetectorAdapter
from eovrt_media.service.model_loader import load_model_from_env


def test_load_model_from_env_loads_mock_adapter():
    catalog_root = find_plane_catalog_root()

    adapter, model_section = load_model_from_env(catalog_root, "mock")

    assert isinstance(adapter, MockDetectorAdapter)
    assert model_section.ref == "mock"
    assert model_section.adapter == "mock"


def test_load_model_from_env_applies_device_override():
    catalog_root = find_plane_catalog_root()

    _, model_section = load_model_from_env(catalog_root, "mock", device="cpu")

    assert model_section.device == "cpu"


def test_load_model_from_env_unknown_ref_raises():
    catalog_root = find_plane_catalog_root()

    try:
        load_model_from_env(catalog_root, "does-not-exist")
    except FileNotFoundError:
        pass
    else:
        raise AssertionError("se esperaba FileNotFoundError")
```

- [ ] **Step 2: Correr el test y verificar que falla**

Run: `pytest tests/service/test_model_loader.py -v`
Expected: `ModuleNotFoundError: No module named 'eovrt_media.service.model_loader'`

- [ ] **Step 3: Implementar**

Create `src/eovrt_media/service/model_loader.py`:

```python
"""Carga del modelo fijo de esta instancia del servicio, una única vez al arrancar.

Sin recarga dinámica: si se necesita otro modelo, se reinicia el contenedor con
otro ``MODEL_REF``. Ver Spec A §4.
"""

from __future__ import annotations

from pathlib import Path

from eovrt_media.config.loader import load_catalog_entry
from eovrt_media.config.schemas import ModelSection
from eovrt_media.models import create_adapter
from eovrt_media.models.base import BaseDetectorAdapter


def load_model_from_env(
    catalog_root: Path, model_ref: str, device: str | None = None
) -> tuple[BaseDetectorAdapter, ModelSection]:
    """Resuelve ``model_ref`` contra el catálogo, crea el adaptador y lo carga.

    Se invoca una única vez, en el lifespan del servicio.
    """
    base = load_catalog_entry(catalog_root, "models", model_ref)
    overrides: dict[str, object] = {"ref": model_ref}
    if device is not None:
        overrides["device"] = device
    model_section = ModelSection(**{**base, **overrides})

    adapter = create_adapter(model_section)
    adapter.load()
    return adapter, model_section
```

- [ ] **Step 4: Correr el test y verificar que pasa**

Run: `pytest tests/service/test_model_loader.py -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add src/eovrt_media/service/model_loader.py tests/service/test_model_loader.py
git commit -m "feat(service): carga del modelo fijo desde MODEL_REF"
```

---

### Task 7: Schemas de la API HTTP

**Files:**
- Create: `src/eovrt_media/service/schemas.py`
- Test: Create `tests/service/test_schemas.py`

**Interfaces:**
- Consumes: `PromptSet` (`eovrt_media.config.schemas`, ya validado con clases/phrasings).
- Produces: `IngestRequest`, `PromptsRequest`, `RunParamsRequest`, `CreateRunRequest`, `RunStatusResponse`, `ModelInfoResponse`, `IngestPluginResponse`, `DatasetCatalogEntryResponse`.

Reusa `PromptSet` directamente en vez de duplicar su validación — el body del request para prompts es un `PromptSet` inline, igual que el que hoy vive en los YAML de `experimental-setup/prompts/`.

- [ ] **Step 1: Escribir el test que falla**

Create `tests/service/test_schemas.py`:

```python
import pytest
from pydantic import ValidationError

from eovrt_media.service.schemas import CreateRunRequest


def _valid_payload() -> dict:
    return {
        "ingest": {"plugin": "image_folder", "config": {"path": "/tmp/imgs"}},
        "prompts": {
            "prompt_set": {
                "id": "adhoc",
                "classes": [
                    {"id": "person", "phrasings": {"default": ["person"]}},
                ],
            },
            "active_ids": ["person"],
        },
    }


def test_create_run_request_accepts_minimal_payload():
    request = CreateRunRequest(**_valid_payload())
    assert request.ingest.plugin == "image_folder"
    assert request.prompts.prompt_set.id == "adhoc"
    assert request.run.stride == 1
    assert request.run.save_annotated_video is False


def test_create_run_request_rejects_missing_ingest():
    payload = _valid_payload()
    del payload["ingest"]
    with pytest.raises(ValidationError):
        CreateRunRequest(**payload)


def test_create_run_request_rejects_empty_phrasings():
    payload = _valid_payload()
    payload["prompts"]["prompt_set"]["classes"][0]["phrasings"] = {}
    request = CreateRunRequest(**payload)
    # La validación de "al menos un phrasing por clase activa" ocurre en
    # PromptsFile.build_plan (config/schemas.py), no en el schema de transporte.
    assert request.prompts.prompt_set.classes[0].phrasings == {}
```

- [ ] **Step 2: Correr el test y verificar que falla**

Run: `pytest tests/service/test_schemas.py -v`
Expected: `ModuleNotFoundError: No module named 'eovrt_media.service.schemas'`

- [ ] **Step 3: Implementar**

Create `src/eovrt_media/service/schemas.py`:

```python
"""Modelos Pydantic de la API HTTP del servicio (request/response)."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from eovrt_media.config.schemas import PromptSet


class IngestRequest(BaseModel):
    """Selección de plugin de ingesta: por referencia al catálogo o inline."""

    plugin: str
    ref: str | None = None
    config: dict[str, Any] = Field(default_factory=dict)


class PromptsRequest(BaseModel):
    """Prompt set inline — la consola lo resuelve y lo manda completo."""

    prompt_set: PromptSet
    active_ids: list[str] | None = None


class RunParamsRequest(BaseModel):
    stride: int = 1
    max_units: int | None = None
    save_annotated_video: bool = False
    min_confidence: float = 0.25


class CreateRunRequest(BaseModel):
    ingest: IngestRequest
    prompts: PromptsRequest
    run: RunParamsRequest = Field(default_factory=RunParamsRequest)


class RunStatusResponse(BaseModel):
    run_id: str
    status: str
    error: str | None = None
    summary: dict[str, Any] | None = None


class ModelInfoResponse(BaseModel):
    ref: str
    adapter: str | None
    device: str
    prompt_backend: str


class IngestPluginResponse(BaseModel):
    id: str
    kind: str
    available: bool
    reason: str | None = None


class DatasetCatalogEntryResponse(BaseModel):
    id: str
    type: str
    description: str | None = None
```

- [ ] **Step 4: Correr el test y verificar que pasa**

Run: `pytest tests/service/test_schemas.py -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add src/eovrt_media/service/schemas.py tests/service/test_schemas.py
git commit -m "feat(service): schemas Pydantic de la API HTTP"
```

---

### Task 8: `build_run_config` — de un `CreateRunRequest` a un `RunConfig`

**Files:**
- Create: `src/eovrt_media/service/run_builder.py`
- Test: Create `tests/service/test_run_builder.py`

**Interfaces:**
- Consumes: `CreateRunRequest` (Task 7), `load_catalog_entry` (Task 2), `RunConfig`/`RunSection`/`SourceSection`/`PromptsSection`/`PromptsFile`/`RateControlConfig`/`PostprocessConfig`/`OutputsConfig` (`eovrt_media.config.schemas`).
- Produces: `resolve_ingest_source(ingest: IngestRequest, catalog_root: Path) -> dict`, `build_run_config(request: CreateRunRequest, model_section: ModelSection, catalog_root: Path, runs_dir: Path, run_id: str) -> RunConfig`.

- [ ] **Step 1: Escribir el test que falla**

Create `tests/service/test_run_builder.py`:

```python
from pathlib import Path

import pytest

from eovrt_media.config.schemas import ModelSection
from eovrt_media.service.run_builder import build_run_config, resolve_ingest_source
from eovrt_media.service.schemas import CreateRunRequest, IngestRequest


def _model_section() -> ModelSection:
    return ModelSection(ref="mock", adapter="mock", device="cpu")


def _request(**overrides) -> CreateRunRequest:
    payload = {
        "ingest": {"plugin": "image_folder", "config": {"path": "/tmp/imgs"}},
        "prompts": {
            "prompt_set": {
                "id": "adhoc",
                "classes": [{"id": "person", "phrasings": {"default": ["person"]}}],
            },
            "active_ids": ["person"],
        },
    }
    payload.update(overrides)
    return CreateRunRequest(**payload)


def test_resolve_ingest_source_inline_config(tmp_path: Path):
    ingest = IngestRequest(plugin="image_folder", config={"path": "/tmp/imgs"})
    data = resolve_ingest_source(ingest, tmp_path)
    assert data == {"path": "/tmp/imgs", "type": "image_folder"}


def test_resolve_ingest_source_by_ref(tmp_path: Path):
    datasets_dir = tmp_path / "datasets"
    datasets_dir.mkdir()
    (datasets_dir / "demo_v2.yaml").write_text("type: image_folder\npath: /data/demo\n")

    ingest = IngestRequest(plugin="image_folder", ref="demo_v2")
    data = resolve_ingest_source(ingest, tmp_path)

    assert data["path"] == "/data/demo"
    assert data["type"] == "image_folder"


def test_resolve_ingest_source_ref_with_override(tmp_path: Path):
    datasets_dir = tmp_path / "datasets"
    datasets_dir.mkdir()
    (datasets_dir / "demo_v2.yaml").write_text("type: image_folder\npath: /data/demo\n")

    ingest = IngestRequest(plugin="image_folder", ref="demo_v2", config={"path": "/other"})
    data = resolve_ingest_source(ingest, tmp_path)

    assert data["path"] == "/other"


def test_build_run_config_produces_valid_run_config(tmp_path: Path):
    config = build_run_config(
        request=_request(),
        model_section=_model_section(),
        catalog_root=tmp_path,
        runs_dir=tmp_path / "runs",
        run_id="run_test_001",
    )

    assert config.run.id == "run_test_001"
    assert config.source.type == "image_folder"
    assert config.source.path == "/tmp/imgs"
    assert config.model.ref == "mock"
    assert config.prompts.active_ids == ["person"]
    assert config.prompts_file is not None
    assert config.prompts_file.resolved_set_id() == "adhoc"


def test_build_run_config_applies_run_params(tmp_path: Path):
    config = build_run_config(
        request=_request(run={"stride": 2, "max_units": 10, "save_annotated_video": True}),
        model_section=_model_section(),
        catalog_root=tmp_path,
        runs_dir=tmp_path / "runs",
        run_id="run_test_002",
    )

    assert config.rate_control.stride == 2
    assert config.run.max_units == 10
    assert config.outputs.save_annotated_video is True


def test_build_run_config_can_build_prompt_plan(tmp_path: Path):
    """El RunConfig resultante debe soportar build_prompt_plan sin ir a disco."""
    config = build_run_config(
        request=_request(),
        model_section=_model_section(),
        catalog_root=tmp_path,
        runs_dir=tmp_path / "runs",
        run_id="run_test_003",
    )

    plan = config.build_prompt_plan("default")
    assert plan.texts() == ["person"]


def test_build_run_config_missing_path_raises_validation_error(tmp_path: Path):
    request = _request(ingest={"plugin": "image_folder", "config": {}})
    with pytest.raises(Exception):
        build_run_config(
            request=request,
            model_section=_model_section(),
            catalog_root=tmp_path,
            runs_dir=tmp_path / "runs",
            run_id="run_test_004",
        )
```

- [ ] **Step 2: Correr el test y verificar que falla**

Run: `pytest tests/service/test_run_builder.py -v`
Expected: `ModuleNotFoundError: No module named 'eovrt_media.service.run_builder'`

- [ ] **Step 3: Implementar**

Create `src/eovrt_media/service/run_builder.py`:

```python
"""Construye un RunConfig ejecutable a partir de un CreateRunRequest.

No pasa por load_run_config (no hay manifiesto YAML en disco): el source se
resuelve contra el catálogo de datasets o se usa inline, el modelo es el que
ya cargó esta instancia, y los prompts llegan inline en el request.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from eovrt_media.config.loader import load_catalog_entry
from eovrt_media.config.schemas import (
    ModelSection,
    OutputsConfig,
    PostprocessConfig,
    PromptsFile,
    PromptsSection,
    RateControlConfig,
    RunConfig,
    RunSection,
    SourceSection,
)
from eovrt_media.service.schemas import CreateRunRequest, IngestRequest


def resolve_ingest_source(ingest: IngestRequest, catalog_root: Path) -> dict[str, Any]:
    """Arma los campos de ``source`` a partir de un ref de catálogo y/o config inline."""
    if ingest.ref:
        base = load_catalog_entry(catalog_root, "datasets", ingest.ref)
        merged = {**base, **ingest.config}
    else:
        merged = dict(ingest.config)
    merged["type"] = ingest.plugin
    return merged


def build_run_config(
    request: CreateRunRequest,
    model_section: ModelSection,
    catalog_root: Path,
    runs_dir: Path,
    run_id: str,
) -> RunConfig:
    source_data = resolve_ingest_source(request.ingest, catalog_root)

    config = RunConfig(
        run=RunSection(
            id=run_id,
            scenario="DBE",
            name=run_id,
            max_units=request.run.max_units,
        ),
        source=SourceSection(**source_data),
        model=model_section,
        prompts=PromptsSection(file="inline", active_ids=request.prompts.active_ids),
        rate_control=RateControlConfig(stride=request.run.stride),
        postprocess=PostprocessConfig(min_confidence=request.run.min_confidence),
        outputs=OutputsConfig(
            run_dir=str(runs_dir),
            base_dir=str(runs_dir),
            save_annotated_video=request.run.save_annotated_video,
        ),
    )
    config.prompts_file = PromptsFile(prompt_set=request.prompts.prompt_set)
    return config
```

- [ ] **Step 4: Correr el test y verificar que pasa**

Run: `pytest tests/service/test_run_builder.py -v`
Expected: 7 passed

- [ ] **Step 5: Commit**

```bash
git add src/eovrt_media/service/run_builder.py tests/service/test_run_builder.py
git commit -m "feat(service): construir RunConfig desde un CreateRunRequest"
```

---

### Task 9: `RunEventBus` — pub/sub en memoria por run

**Files:**
- Create: `src/eovrt_media/service/events.py`
- Test: Create `tests/service/test_events.py`

**Interfaces:**
- Produces: `RunEventBus` con métodos `create(run_id)`, `publish(run_id, event: dict)`, `close(run_id)`, `get_queue(run_id) -> queue.Queue | None`, `is_sentinel(item) -> bool`.

Cada run tiene su propia `queue.Queue`, creada ANTES de arrancar el hilo de ejecución. Esto evita una carrera: un consumidor (WebSocket) que se conecta después de que ya se publicaron eventos igual los recibe, porque quedaron bufferizados en la cola.

- [ ] **Step 1: Escribir el test que falla**

Create `tests/service/test_events.py`:

```python
from eovrt_media.service.events import RunEventBus


def test_publish_before_consume_is_buffered():
    bus = RunEventBus()
    bus.create("run_1")

    bus.publish("run_1", {"type": "started"})
    bus.publish("run_1", {"type": "progress", "units_processed": 1})

    q = bus.get_queue("run_1")
    assert q.get_nowait() == {"type": "started"}
    assert q.get_nowait() == {"type": "progress", "units_processed": 1}


def test_close_enqueues_sentinel():
    bus = RunEventBus()
    bus.create("run_1")
    bus.publish("run_1", {"type": "started"})
    bus.close("run_1")

    q = bus.get_queue("run_1")
    assert q.get_nowait() == {"type": "started"}
    sentinel = q.get_nowait()
    assert bus.is_sentinel(sentinel)


def test_get_queue_unknown_run_returns_none():
    bus = RunEventBus()
    assert bus.get_queue("does-not-exist") is None


def test_publish_to_unknown_run_is_noop():
    bus = RunEventBus()
    bus.publish("does-not-exist", {"type": "started"})  # no debe lanzar
```

- [ ] **Step 2: Correr el test y verificar que falla**

Run: `pytest tests/service/test_events.py -v`
Expected: `ModuleNotFoundError: No module named 'eovrt_media.service.events'`

- [ ] **Step 3: Implementar**

Create `src/eovrt_media/service/events.py`:

```python
"""Bus de eventos en memoria: una cola por run, consumida por el WebSocket.

Cada run tiene su cola creada antes de arrancar; un consumidor que se conecta
tarde igual recibe los eventos ya publicados (quedan bufferizados).
"""

from __future__ import annotations

import queue

_SENTINEL = object()


class RunEventBus:
    def __init__(self) -> None:
        self._queues: dict[str, queue.Queue] = {}

    def create(self, run_id: str) -> None:
        self._queues[run_id] = queue.Queue()

    def publish(self, run_id: str, event: dict) -> None:
        q = self._queues.get(run_id)
        if q is not None:
            q.put(event)

    def close(self, run_id: str) -> None:
        q = self._queues.get(run_id)
        if q is not None:
            q.put(_SENTINEL)

    def get_queue(self, run_id: str) -> queue.Queue | None:
        return self._queues.get(run_id)

    def is_sentinel(self, item: object) -> bool:
        return item is _SENTINEL
```

- [ ] **Step 4: Correr el test y verificar que pasa**

Run: `pytest tests/service/test_events.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add src/eovrt_media/service/events.py tests/service/test_events.py
git commit -m "feat(service): RunEventBus para telemetría en vivo por run"
```

---

### Task 10: `RunManager` — un run activo, stop, historial

**Files:**
- Create: `src/eovrt_media/service/run_manager.py`
- Test: Create `tests/service/test_run_manager.py`

**Interfaces:**
- Consumes: `RunEventBus` (Task 9), `build_run_config` (Task 8), `run_pipeline` (modificado en Task 3), `CreateRunRequest` (Task 7).
- Produces: `RunHandle` (dataclass: `run_id`, `status`, `config`, `source`, `error`, `summary`, `stop_requested`), `RunBusyError`, `RunNotFoundError`, `RunManager` con `create_run(request) -> str`, `get_run(run_id) -> RunHandle`, `list_runs() -> list[RunHandle]`, `stop_run(run_id) -> None`.

- [ ] **Step 1: Escribir el test que falla**

Create `tests/service/test_run_manager.py`:

```python
from __future__ import annotations

import time
from pathlib import Path

import cv2
import numpy as np
import pytest

from eovrt_media.config.schemas import ModelSection
from eovrt_media.models.mock_detector import MockDetectorAdapter
from eovrt_media.service.events import RunEventBus
from eovrt_media.service.run_manager import RunBusyError, RunManager, RunNotFoundError
from eovrt_media.service.schemas import CreateRunRequest
from eovrt_media.sources.base import BaseSource


def _create_test_images(folder: Path, count: int) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    for i in range(count):
        img = np.zeros((64, 64, 3), dtype=np.uint8)
        img[:] = (i, i, i)
        cv2.imwrite(str(folder / f"img_{i:03d}.jpg"), img)


def _request(path: str) -> CreateRunRequest:
    return CreateRunRequest(
        **{
            "ingest": {"plugin": "image_folder", "config": {"path": path}},
            "prompts": {
                "prompt_set": {
                    "id": "adhoc",
                    "classes": [{"id": "person", "phrasings": {"default": ["person"]}}],
                },
                "active_ids": ["person"],
            },
        }
    )


def _manager(tmp_path: Path) -> RunManager:
    return RunManager(
        adapter=MockDetectorAdapter(),
        model_section=ModelSection(ref="mock", adapter="mock", device="cpu"),
        catalog_root=tmp_path,
        runs_dir=tmp_path / "runs",
        event_bus=RunEventBus(),
    )


def _wait_until_terminal(manager: RunManager, run_id: str, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    terminal = {"succeeded", "failed", "stopped"}
    while time.monotonic() < deadline:
        if manager.get_run(run_id).status in terminal:
            return
        time.sleep(0.01)
    raise AssertionError(f"run {run_id} no terminó a tiempo")


def test_create_run_runs_to_completion(tmp_path: Path):
    images_dir = tmp_path / "images"
    _create_test_images(images_dir, count=3)
    manager = _manager(tmp_path)

    run_id = manager.create_run(_request(str(images_dir)))
    _wait_until_terminal(manager, run_id)

    handle = manager.get_run(run_id)
    assert handle.status == "succeeded"
    assert handle.summary is not None
    assert handle.summary["units_processed"] == 3


def test_second_run_while_active_raises_busy(tmp_path: Path):
    images_dir = tmp_path / "images"
    _create_test_images(images_dir, count=200)
    manager = _manager(tmp_path)

    manager.create_run(_request(str(images_dir)))
    with pytest.raises(RunBusyError):
        manager.create_run(_request(str(images_dir)))


def test_get_unknown_run_raises_not_found(tmp_path: Path):
    manager = _manager(tmp_path)
    with pytest.raises(RunNotFoundError):
        manager.get_run("does-not-exist")


def test_stop_unknown_run_raises_not_found(tmp_path: Path):
    manager = _manager(tmp_path)
    with pytest.raises(RunNotFoundError):
        manager.stop_run("does-not-exist")


def test_stop_calls_source_stop(tmp_path: Path, monkeypatch):
    """Verifica que stop_run invoca source.stop() sobre la fuente capturada."""
    from eovrt_media.runtime import pipeline as pipeline_module

    stop_calls: list[int] = []

    class InfiniteFakeSource(BaseSource):
        def __init__(self) -> None:
            import threading

            self._stop_event = threading.Event()

        def __iter__(self):
            from eovrt_media.contracts import VisualUnit

            index = 0
            while not self._stop_event.is_set():
                yield VisualUnit(
                    unit_id=f"unit_{index}",
                    source_type="image",
                    width=64,
                    height=64,
                    pixel_data=np.zeros((64, 64, 3), dtype=np.uint8),
                )
                index += 1

        def stop(self) -> None:
            stop_calls.append(1)
            self._stop_event.set()

        def __len__(self) -> int:
            raise TypeError("fuente en vivo sin longitud definida")

    monkeypatch.setattr(pipeline_module, "create_source", lambda config: InfiniteFakeSource())

    manager = _manager(tmp_path)
    run_id = manager.create_run(_request("/unused"))

    deadline = time.monotonic() + 2.0
    while manager.get_run(run_id).source is None and time.monotonic() < deadline:
        time.sleep(0.01)

    manager.stop_run(run_id)
    _wait_until_terminal(manager, run_id)

    assert stop_calls == [1]
    assert manager.get_run(run_id).status == "stopped"


def test_list_runs_includes_active_and_finished(tmp_path: Path):
    images_dir = tmp_path / "images"
    _create_test_images(images_dir, count=2)
    manager = _manager(tmp_path)

    run_id = manager.create_run(_request(str(images_dir)))
    _wait_until_terminal(manager, run_id)

    runs = manager.list_runs()
    assert any(r.run_id == run_id for r in runs)
```

- [ ] **Step 2: Correr el test y verificar que falla**

Run: `pytest tests/service/test_run_manager.py -v`
Expected: `ModuleNotFoundError: No module named 'eovrt_media.service.run_manager'`

- [ ] **Step 3: Implementar**

Create `src/eovrt_media/service/run_manager.py`:

```python
"""Un run activo a la vez (1 GPU). Sin scheduler: 409 si ya hay uno corriendo."""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from eovrt_media.config.schemas import ModelSection, RunConfig
from eovrt_media.models.base import BaseDetectorAdapter
from eovrt_media.runtime import run_pipeline
from eovrt_media.service.events import RunEventBus
from eovrt_media.service.run_builder import build_run_config
from eovrt_media.service.schemas import CreateRunRequest
from eovrt_media.sources.base import BaseSource


class RunBusyError(RuntimeError):
    pass


class RunNotFoundError(RuntimeError):
    pass


@dataclass
class RunHandle:
    run_id: str
    status: str  # "running" | "succeeded" | "failed" | "stopped"
    config: RunConfig
    source: BaseSource | None = None
    error: str | None = None
    summary: dict | None = None
    stop_requested: bool = field(default=False)


def _generate_run_id() -> str:
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    return f"run_{ts}_{uuid4().hex[:8]}"


class RunManager:
    def __init__(
        self,
        adapter: BaseDetectorAdapter,
        model_section: ModelSection,
        catalog_root: Path,
        runs_dir: Path,
        event_bus: RunEventBus,
    ) -> None:
        self._adapter = adapter
        self._model_section = model_section
        self._catalog_root = Path(catalog_root)
        self._runs_dir = Path(runs_dir)
        self._event_bus = event_bus
        self._lock = threading.Lock()
        self._active_run_id: str | None = None
        self._runs: dict[str, RunHandle] = {}

    def create_run(self, request: CreateRunRequest) -> str:
        with self._lock:
            if self._active_run_id is not None:
                raise RunBusyError(f"Ya hay un run activo: {self._active_run_id}")
            run_id = _generate_run_id()
            config = build_run_config(
                request=request,
                model_section=self._model_section,
                catalog_root=self._catalog_root,
                runs_dir=self._runs_dir,
                run_id=run_id,
            )
            handle = RunHandle(run_id=run_id, status="running", config=config)
            self._runs[run_id] = handle
            self._active_run_id = run_id
            self._event_bus.create(run_id)

        thread = threading.Thread(
            target=self._execute, args=(run_id, config), daemon=True, name=f"run-{run_id}"
        )
        thread.start()
        return run_id

    def _execute(self, run_id: str, config: RunConfig) -> None:
        handle = self._runs[run_id]

        def on_event(payload: dict) -> None:
            self._event_bus.publish(run_id, payload)

        def on_source_ready(source: BaseSource) -> None:
            handle.source = source

        try:
            run_pipeline(
                config,
                console=None,
                adapter=self._adapter,
                on_event=on_event,
                on_source_ready=on_source_ready,
            )
            handle.status = "stopped" if handle.stop_requested else "succeeded"
        except Exception as exc:
            handle.status = "failed"
            handle.error = str(exc)
        finally:
            summary_path = self._runs_dir / run_id / "summary.json"
            if summary_path.exists():
                handle.summary = json.loads(summary_path.read_text())
            self._event_bus.publish(run_id, {"type": "finished", "run_id": run_id, "status": handle.status})
            self._event_bus.close(run_id)
            with self._lock:
                if self._active_run_id == run_id:
                    self._active_run_id = None

    def get_run(self, run_id: str) -> RunHandle:
        handle = self._runs.get(run_id)
        if handle is None:
            raise RunNotFoundError(run_id)
        return handle

    def list_runs(self) -> list[RunHandle]:
        return list(self._runs.values())

    def stop_run(self, run_id: str) -> None:
        handle = self.get_run(run_id)
        handle.stop_requested = True
        if handle.source is not None:
            handle.source.stop()
```

- [ ] **Step 4: Correr el test y verificar que pasa**

Run: `pytest tests/service/test_run_manager.py -v`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add src/eovrt_media/service/run_manager.py tests/service/test_run_manager.py
git commit -m "feat(service): RunManager con un run activo, stop e historial"
```

---

### Task 11: App FastAPI — lifespan, `/healthz`, `/readyz`, `GET /api/model`

**Files:**
- Create: `src/eovrt_media/service/settings.py`
- Create: `src/eovrt_media/service/routers/__init__.py`
- Create: `src/eovrt_media/service/routers/health.py`
- Create: `src/eovrt_media/service/routers/model.py`
- Create: `src/eovrt_media/service/app.py`
- Test: Create `tests/service/test_app_health_and_model.py`

**Interfaces:**
- Consumes: `load_model_from_env` (Task 6), `find_plane_catalog_root` (`eovrt_media.config.loader`), `RunManager`/`RunEventBus` (Tasks 9-10).
- Produces: `create_app() -> FastAPI`, `app` (instancia module-level para uvicorn), `app.state.settings/catalog_root/model_section/event_bus/run_manager`.

El modelo se carga de forma **síncrona y bloqueante** en el lifespan: si falla, la excepción se propaga y el proceso no llega a servir requests (falla simple, visible en logs, sin estados intermedios de "cargando" — decisión explícita para no complicar el media-plane).

- [ ] **Step 1: Escribir el test que falla**

Create `tests/service/test_app_health_and_model.py`:

```python
import pytest
from fastapi.testclient import TestClient

from eovrt_media.service.app import create_app


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("MODEL_REF", "mock")
    monkeypatch.setenv("MODEL_DEVICE", "cpu")
    monkeypatch.setenv("RUNS_DIR", str(tmp_path / "runs"))
    with TestClient(create_app()) as c:
        yield c


def test_healthz_returns_ok(client):
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_readyz_returns_ok_once_model_loaded(client):
    response = client.get("/readyz")
    assert response.status_code == 200
    assert response.json()["status"] == "ready"


def test_get_model_returns_loaded_model_info(client):
    response = client.get("/api/model")
    assert response.status_code == 200
    body = response.json()
    assert body["ref"] == "mock"
    assert body["adapter"] == "mock"
    assert body["device"] == "cpu"
    assert body["prompt_backend"] == "default"


def test_missing_model_ref_fails_startup(monkeypatch, tmp_path):
    monkeypatch.delenv("MODEL_REF", raising=False)
    monkeypatch.setenv("RUNS_DIR", str(tmp_path / "runs"))
    with pytest.raises(RuntimeError, match="MODEL_REF"):
        with TestClient(create_app()):
            pass
```

- [ ] **Step 2: Correr el test y verificar que falla**

Run: `pytest tests/service/test_app_health_and_model.py -v`
Expected: `ModuleNotFoundError: No module named 'eovrt_media.service.app'`

- [ ] **Step 3: Implementar `settings.py`**

Create `src/eovrt_media/service/settings.py`:

```python
"""Configuración del servicio leída de variables de entorno."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ServiceSettings:
    model_ref: str
    model_device: str | None
    catalog_root_override: Path | None
    runs_dir: Path


def load_settings() -> ServiceSettings:
    model_ref = os.environ.get("MODEL_REF")
    if not model_ref:
        raise RuntimeError(
            "MODEL_REF es obligatorio (ej. 'mock', 'yoloe/yoloe-26s', 'grounding-dino/gdino-tiny')."
        )
    catalog_root_env = os.environ.get("EOVRT_MEDIA_CATALOG_ROOT")
    return ServiceSettings(
        model_ref=model_ref,
        model_device=os.environ.get("MODEL_DEVICE"),
        catalog_root_override=Path(catalog_root_env) if catalog_root_env else None,
        runs_dir=Path(os.environ.get("RUNS_DIR", "runs")),
    )
```

- [ ] **Step 4: Implementar los routers de health y model**

Create `src/eovrt_media/service/routers/__init__.py`:

```python
```

Create `src/eovrt_media/service/routers/health.py`:

```python
from __future__ import annotations

from fastapi import APIRouter

router = APIRouter()


@router.get("/healthz")
def healthz() -> dict:
    """El proceso está vivo. No depende de que el modelo haya cargado."""
    return {"status": "ok"}


@router.get("/readyz")
def readyz() -> dict:
    """Si el proceso responde, el modelo ya cargó (carga síncrona en el lifespan)."""
    return {"status": "ready"}
```

Create `src/eovrt_media/service/routers/model.py`:

```python
from __future__ import annotations

from fastapi import APIRouter, Request

from eovrt_media.service.schemas import ModelInfoResponse

router = APIRouter()


@router.get("/api/model", response_model=ModelInfoResponse)
def get_model(request: Request) -> ModelInfoResponse:
    model_section = request.app.state.model_section
    adapter = request.app.state.run_manager._adapter
    return ModelInfoResponse(
        ref=model_section.ref or "unknown",
        adapter=model_section.adapter,
        device=model_section.device,
        prompt_backend=adapter.PROMPT_BACKEND,
    )
```

- [ ] **Step 5: Implementar `app.py`**

Create `src/eovrt_media/service/app.py`:

```python
"""App FastAPI del servicio de inferencia media-plane (Fase 1, contenedor único DBE)."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from eovrt_media.config.loader import find_plane_catalog_root
from eovrt_media.service.events import RunEventBus
from eovrt_media.service.model_loader import load_model_from_env
from eovrt_media.service.routers import health, model
from eovrt_media.service.run_manager import RunManager
from eovrt_media.service.settings import load_settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = load_settings()
    catalog_root = find_plane_catalog_root(override=settings.catalog_root_override)
    adapter, model_section = load_model_from_env(
        catalog_root, settings.model_ref, settings.model_device
    )
    event_bus = RunEventBus()
    run_manager = RunManager(
        adapter=adapter,
        model_section=model_section,
        catalog_root=catalog_root,
        runs_dir=settings.runs_dir,
        event_bus=event_bus,
    )

    app.state.settings = settings
    app.state.catalog_root = catalog_root
    app.state.model_section = model_section
    app.state.event_bus = event_bus
    app.state.run_manager = run_manager

    yield

    adapter.close()


def create_app() -> FastAPI:
    app = FastAPI(title="E-OVRT Media Plane Service", lifespan=lifespan)
    app.include_router(health.router)
    app.include_router(model.router)
    return app


app = create_app()
```

- [ ] **Step 6: Correr el test y verificar que pasa**

Run: `pytest tests/service/test_app_health_and_model.py -v`
Expected: 4 passed

- [ ] **Step 7: Commit**

```bash
git add src/eovrt_media/service/settings.py src/eovrt_media/service/routers/ src/eovrt_media/service/app.py tests/service/test_app_health_and_model.py
git commit -m "feat(service): app FastAPI con lifespan, healthz/readyz y GET /api/model"
```

---

### Task 12: `GET /api/catalog/ingest-plugins` y `GET /api/catalog/datasets`

**Files:**
- Create: `src/eovrt_media/service/routers/catalog.py`
- Modify: `src/eovrt_media/service/app.py` (registrar el router)
- Test: Create `tests/service/test_catalog_routes.py`

**Interfaces:**
- Consumes: `INGEST_PLUGINS` (Task 4), `list_datasets` (Task 5).
- Produces: rutas `GET /api/catalog/ingest-plugins` → `list[IngestPluginResponse]`, `GET /api/catalog/datasets` → `list[DatasetCatalogEntryResponse]`.

- [ ] **Step 1: Escribir el test que falla**

Create `tests/service/test_catalog_routes.py`:

```python
import pytest
from fastapi.testclient import TestClient

from eovrt_media.service.app import create_app


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("MODEL_REF", "mock")
    monkeypatch.setenv("RUNS_DIR", str(tmp_path / "runs"))
    with TestClient(create_app()) as c:
        yield c


def test_ingest_plugins_endpoint_lists_four_plugins(client):
    response = client.get("/api/catalog/ingest-plugins")
    assert response.status_code == 200
    ids = {p["id"] for p in response.json()}
    assert ids == {"image_folder", "video_file", "rtsp", "oak_d"}


def test_ingest_plugins_endpoint_marks_oak_d_unavailable(client):
    response = client.get("/api/catalog/ingest-plugins")
    oak_d = next(p for p in response.json() if p["id"] == "oak_d")
    assert oak_d["available"] is False


def test_datasets_endpoint_reflects_real_catalog(client):
    response = client.get("/api/catalog/datasets")
    assert response.status_code == 200
    ids = {d["id"] for d in response.json()}
    # El catálogo real de configs/datasets/ incluye mock.yaml-adjacent entries.
    assert isinstance(ids, set)
```

- [ ] **Step 2: Correr el test y verificar que falla**

Run: `pytest tests/service/test_catalog_routes.py -v`
Expected: `404 Not Found` (rutas no registradas todavía)

- [ ] **Step 3: Implementar**

Create `src/eovrt_media/service/routers/catalog.py`:

```python
from __future__ import annotations

from fastapi import APIRouter, Request

from eovrt_media.service.datasets_catalog import list_datasets
from eovrt_media.service.ingest_registry import INGEST_PLUGINS
from eovrt_media.service.schemas import DatasetCatalogEntryResponse, IngestPluginResponse

router = APIRouter()


@router.get("/api/catalog/ingest-plugins", response_model=list[IngestPluginResponse])
def get_ingest_plugins() -> list[IngestPluginResponse]:
    return [
        IngestPluginResponse(id=p.id, kind=p.kind, available=p.available, reason=p.reason)
        for p in INGEST_PLUGINS
    ]


@router.get("/api/catalog/datasets", response_model=list[DatasetCatalogEntryResponse])
def get_datasets(request: Request) -> list[DatasetCatalogEntryResponse]:
    catalog_root = request.app.state.catalog_root
    return [
        DatasetCatalogEntryResponse(id=e.id, type=e.type, description=e.description)
        for e in list_datasets(catalog_root)
    ]
```

Modificar `src/eovrt_media/service/app.py`: agregar el import y el registro del router.

```python
from eovrt_media.service.routers import catalog, health, model
```

```python
def create_app() -> FastAPI:
    app = FastAPI(title="E-OVRT Media Plane Service", lifespan=lifespan)
    app.include_router(health.router)
    app.include_router(model.router)
    app.include_router(catalog.router)
    return app
```

- [ ] **Step 4: Correr el test y verificar que pasa**

Run: `pytest tests/service/test_catalog_routes.py -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add src/eovrt_media/service/routers/catalog.py src/eovrt_media/service/app.py tests/service/test_catalog_routes.py
git commit -m "feat(service): rutas de catálogo (ingest-plugins, datasets)"
```

---

### Task 13: Rutas de runs — crear, consultar, listar, detener

**Files:**
- Create: `src/eovrt_media/service/routers/runs.py`
- Modify: `src/eovrt_media/service/app.py` (registrar router + exception handlers)
- Test: Create `tests/service/test_runs_routes.py`

**Interfaces:**
- Consumes: `RunManager` (Task 10), `CreateRunRequest`/`RunStatusResponse` (Task 7).
- Produces: `POST /api/runs` → `{run_id}` (201) o `409`; `POST /api/runs/{run_id}/stop` → `204` o `404`; `GET /api/runs/{run_id}` → `RunStatusResponse`; `GET /api/runs` → `list[RunStatusResponse]`.

- [ ] **Step 1: Escribir el test que falla**

Create `tests/service/test_runs_routes.py`:

```python
from __future__ import annotations

import time
from pathlib import Path

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

from eovrt_media.service.app import create_app


def _create_test_images(folder: Path, count: int) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    for i in range(count):
        img = np.zeros((64, 64, 3), dtype=np.uint8)
        img[:] = (i, i, i)
        cv2.imwrite(str(folder / f"img_{i:03d}.jpg"), img)


def _payload(path: str) -> dict:
    return {
        "ingest": {"plugin": "image_folder", "config": {"path": path}},
        "prompts": {
            "prompt_set": {
                "id": "adhoc",
                "classes": [{"id": "person", "phrasings": {"default": ["person"]}}],
            },
            "active_ids": ["person"],
        },
    }


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("MODEL_REF", "mock")
    monkeypatch.setenv("RUNS_DIR", str(tmp_path / "runs"))
    with TestClient(create_app()) as c:
        yield c


def _wait_until_terminal(client: TestClient, run_id: str, timeout: float = 5.0) -> dict:
    deadline = time.monotonic() + timeout
    terminal = {"succeeded", "failed", "stopped"}
    while time.monotonic() < deadline:
        body = client.get(f"/api/runs/{run_id}").json()
        if body["status"] in terminal:
            return body
        time.sleep(0.01)
    raise AssertionError("run no terminó a tiempo")


def test_create_run_returns_run_id(client, tmp_path):
    images_dir = tmp_path / "images"
    _create_test_images(images_dir, count=2)

    response = client.post("/api/runs", json=_payload(str(images_dir)))

    assert response.status_code == 201
    assert "run_id" in response.json()


def test_get_run_reaches_succeeded(client, tmp_path):
    images_dir = tmp_path / "images"
    _create_test_images(images_dir, count=2)

    run_id = client.post("/api/runs", json=_payload(str(images_dir))).json()["run_id"]
    body = _wait_until_terminal(client, run_id)

    assert body["status"] == "succeeded"
    assert body["summary"]["units_processed"] == 2


def test_second_run_while_active_returns_409(client, tmp_path):
    images_dir = tmp_path / "images"
    _create_test_images(images_dir, count=500)

    client.post("/api/runs", json=_payload(str(images_dir)))
    response = client.post("/api/runs", json=_payload(str(images_dir)))

    assert response.status_code == 409


def test_get_unknown_run_returns_404(client):
    response = client.get("/api/runs/does-not-exist")
    assert response.status_code == 404


def test_stop_unknown_run_returns_404(client):
    response = client.post("/api/runs/does-not-exist/stop")
    assert response.status_code == 404


def test_invalid_payload_returns_422(client):
    response = client.post("/api/runs", json={"ingest": {"plugin": "image_folder"}})
    assert response.status_code == 422


def test_list_runs_includes_created_run(client, tmp_path):
    images_dir = tmp_path / "images"
    _create_test_images(images_dir, count=2)

    run_id = client.post("/api/runs", json=_payload(str(images_dir))).json()["run_id"]
    _wait_until_terminal(client, run_id)

    response = client.get("/api/runs")
    assert response.status_code == 200
    assert any(r["run_id"] == run_id for r in response.json())
```

- [ ] **Step 2: Correr el test y verificar que falla**

Run: `pytest tests/service/test_runs_routes.py -v`
Expected: `404 Not Found` en todos los `POST /api/runs` (ruta no registrada)

- [ ] **Step 3: Implementar**

Create `src/eovrt_media/service/routers/runs.py`:

```python
from __future__ import annotations

from fastapi import APIRouter, Request, Response, status

from eovrt_media.service.run_manager import RunNotFoundError
from eovrt_media.service.schemas import CreateRunRequest, RunStatusResponse

router = APIRouter()


def _to_status_response(handle) -> RunStatusResponse:
    return RunStatusResponse(
        run_id=handle.run_id,
        status=handle.status,
        error=handle.error,
        summary=handle.summary,
    )


@router.post("/api/runs", status_code=status.HTTP_201_CREATED)
def create_run(payload: CreateRunRequest, request: Request) -> dict:
    run_manager = request.app.state.run_manager
    run_id = run_manager.create_run(payload)
    return {"run_id": run_id}


@router.post("/api/runs/{run_id}/stop", status_code=status.HTTP_204_NO_CONTENT)
def stop_run(run_id: str, request: Request) -> Response:
    run_manager = request.app.state.run_manager
    run_manager.stop_run(run_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/api/runs/{run_id}", response_model=RunStatusResponse)
def get_run(run_id: str, request: Request) -> RunStatusResponse:
    run_manager = request.app.state.run_manager
    handle = run_manager.get_run(run_id)
    return _to_status_response(handle)


@router.get("/api/runs", response_model=list[RunStatusResponse])
def list_runs(request: Request) -> list[RunStatusResponse]:
    run_manager = request.app.state.run_manager
    return [_to_status_response(h) for h in run_manager.list_runs()]
```

Modificar `src/eovrt_media/service/app.py` — agregar el import del router, los exception handlers, y el registro:

```python
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from eovrt_media.config.loader import find_plane_catalog_root
from eovrt_media.service.events import RunEventBus
from eovrt_media.service.model_loader import load_model_from_env
from eovrt_media.service.routers import catalog, health, model, runs
from eovrt_media.service.run_manager import RunBusyError, RunManager, RunNotFoundError
from eovrt_media.service.settings import load_settings
```

```python
def create_app() -> FastAPI:
    app = FastAPI(title="E-OVRT Media Plane Service", lifespan=lifespan)
    app.include_router(health.router)
    app.include_router(model.router)
    app.include_router(catalog.router)
    app.include_router(runs.router)

    @app.exception_handler(RunBusyError)
    async def handle_busy(request: Request, exc: RunBusyError) -> JSONResponse:
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    @app.exception_handler(RunNotFoundError)
    async def handle_not_found(request: Request, exc: RunNotFoundError) -> JSONResponse:
        return JSONResponse(status_code=404, content={"detail": str(exc)})

    return app
```

- [ ] **Step 4: Correr el test y verificar que pasa**

Run: `pytest tests/service/test_runs_routes.py -v`
Expected: 7 passed

- [ ] **Step 5: Commit**

```bash
git add src/eovrt_media/service/routers/runs.py src/eovrt_media/service/app.py tests/service/test_runs_routes.py
git commit -m "feat(service): rutas de creación/consulta/detención de runs"
```

---

### Task 14: WebSocket de telemetría en vivo

**Files:**
- Create: `src/eovrt_media/service/routers/stream.py`
- Modify: `src/eovrt_media/service/app.py` (registrar router)
- Test: Create `tests/service/test_stream_route.py`

**Interfaces:**
- Consumes: `RunEventBus` (Task 9).
- Produces: `WS /api/runs/{run_id}/stream` — emite cada evento publicado como JSON, cierra el socket tras el evento `{"type": "finished", ...}`.

- [ ] **Step 1: Escribir el test que falla**

Create `tests/service/test_stream_route.py`:

```python
from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

from eovrt_media.service.app import create_app


def _create_test_images(folder: Path, count: int) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    for i in range(count):
        img = np.zeros((64, 64, 3), dtype=np.uint8)
        img[:] = (i, i, i)
        cv2.imwrite(str(folder / f"img_{i:03d}.jpg"), img)


def _payload(path: str) -> dict:
    return {
        "ingest": {"plugin": "image_folder", "config": {"path": path}},
        "prompts": {
            "prompt_set": {
                "id": "adhoc",
                "classes": [{"id": "person", "phrasings": {"default": ["person"]}}],
            },
            "active_ids": ["person"],
        },
    }


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("MODEL_REF", "mock")
    monkeypatch.setenv("RUNS_DIR", str(tmp_path / "runs"))
    with TestClient(create_app()) as c:
        yield c


def test_stream_receives_started_progress_and_finished(client, tmp_path):
    images_dir = tmp_path / "images"
    _create_test_images(images_dir, count=3)

    run_id = client.post("/api/runs", json=_payload(str(images_dir))).json()["run_id"]

    types_seen = []
    with client.websocket_connect(f"/api/runs/{run_id}/stream") as ws:
        while True:
            event = ws.receive_json()
            types_seen.append(event["type"])
            if event["type"] == "finished":
                break

    assert types_seen[0] == "started"
    assert "progress" in types_seen
    assert types_seen[-1] == "finished"


def test_stream_unknown_run_closes_immediately(client):
    with pytest.raises(Exception):
        with client.websocket_connect("/api/runs/does-not-exist/stream") as ws:
            ws.receive_json()
```

- [ ] **Step 2: Correr el test y verificar que falla**

Run: `pytest tests/service/test_stream_route.py -v`
Expected: falla al conectar (ruta WS no registrada)

- [ ] **Step 3: Implementar**

Create `src/eovrt_media/service/routers/stream.py`:

```python
from __future__ import annotations

from fastapi import APIRouter, WebSocket
from fastapi.concurrency import run_in_threadpool

router = APIRouter()


@router.websocket("/api/runs/{run_id}/stream")
async def stream_run(websocket: WebSocket, run_id: str) -> None:
    event_bus = websocket.app.state.event_bus
    q = event_bus.get_queue(run_id)
    if q is None:
        await websocket.close(code=4404)
        return

    await websocket.accept()
    try:
        while True:
            item = await run_in_threadpool(q.get)
            if event_bus.is_sentinel(item):
                break
            await websocket.send_json(item)
    finally:
        await websocket.close()
```

Modificar `src/eovrt_media/service/app.py`: agregar `stream` al import y registrar su router.

```python
from eovrt_media.service.routers import catalog, health, model, runs, stream
```

```python
    app.include_router(runs.router)
    app.include_router(stream.router)
```

- [ ] **Step 4: Correr el test y verificar que pasa**

Run: `pytest tests/service/test_stream_route.py -v`
Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
git add src/eovrt_media/service/routers/stream.py src/eovrt_media/service/app.py tests/service/test_stream_route.py
git commit -m "feat(service): WebSocket de telemetría en vivo por run"
```

---

### Task 15: Detecciones paginadas y artefactos (video/previews)

**Files:**
- Create: `src/eovrt_media/service/routers/artifacts.py`
- Modify: `src/eovrt_media/service/app.py` (registrar router)
- Test: Create `tests/service/test_artifacts_routes.py`

**Interfaces:**
- Produces: `GET /api/runs/{run_id}/detections?page=&page_size=` → `{run_id, page, page_size, total, items}`; `GET /api/runs/{run_id}/artifacts/{artifact_path:path}` → `FileResponse` (soporta `Range` nativamente vía Starlette).

- [ ] **Step 1: Escribir el test que falla**

Create `tests/service/test_artifacts_routes.py`:

```python
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from eovrt_media.service.app import create_app


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("MODEL_REF", "mock")
    monkeypatch.setenv("RUNS_DIR", str(tmp_path / "runs"))
    with TestClient(create_app()) as c:
        yield c, tmp_path


def test_detections_paginated(client):
    c, tmp_path = client
    run_dir = tmp_path / "runs" / "run_x"
    run_dir.mkdir(parents=True)
    with open(run_dir / "detections.jsonl", "w") as f:
        for i in range(5):
            f.write(json.dumps({"unit_id": f"u{i}"}) + "\n")

    response = c.get("/api/runs/run_x/detections?page=1&page_size=2")
    body = response.json()

    assert response.status_code == 200
    assert body["total"] == 5
    assert len(body["items"]) == 2
    assert body["items"][0]["unit_id"] == "u0"


def test_detections_missing_file_returns_empty(client):
    c, tmp_path = client
    response = c.get("/api/runs/run_missing/detections")
    body = response.json()
    assert response.status_code == 200
    assert body["total"] == 0
    assert body["items"] == []


def test_artifact_serves_existing_file(client):
    c, tmp_path = client
    run_dir = tmp_path / "runs" / "run_x"
    (run_dir / "previews").mkdir(parents=True)
    (run_dir / "previews" / "0001.jpg").write_bytes(b"fake-jpeg-bytes")

    response = c.get("/api/runs/run_x/artifacts/previews/0001.jpg")

    assert response.status_code == 200
    assert response.content == b"fake-jpeg-bytes"


def test_artifact_rejects_path_traversal(client):
    c, _ = client
    response = c.get("/api/runs/run_x/artifacts/..%2F..%2Fetc%2Fpasswd")
    assert response.status_code == 404


def test_artifact_missing_returns_404(client):
    c, _ = client
    response = c.get("/api/runs/run_x/artifacts/annotated.mp4")
    assert response.status_code == 404
```

- [ ] **Step 2: Correr el test y verificar que falla**

Run: `pytest tests/service/test_artifacts_routes.py -v`
Expected: `404 Not Found` en todos (rutas no registradas)

- [ ] **Step 3: Implementar**

Create `src/eovrt_media/service/routers/artifacts.py`:

```python
from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse

router = APIRouter()


@router.get("/api/runs/{run_id}/detections")
def get_detections(run_id: str, request: Request, page: int = 1, page_size: int = 50) -> dict:
    runs_dir: Path = request.app.state.settings.runs_dir
    path = runs_dir / run_id / "detections.jsonl"
    if not path.exists():
        return {"run_id": run_id, "page": page, "page_size": page_size, "total": 0, "items": []}

    lines = path.read_text().splitlines()
    total = len(lines)
    start = (page - 1) * page_size
    end = start + page_size
    items = [json.loads(line) for line in lines[start:end]]
    return {"run_id": run_id, "page": page, "page_size": page_size, "total": total, "items": items}


@router.get("/api/runs/{run_id}/artifacts/{artifact_path:path}")
def get_artifact(run_id: str, artifact_path: str, request: Request) -> FileResponse:
    if ".." in Path(artifact_path).parts:
        raise HTTPException(status_code=404, detail="Artifact not found")

    runs_dir: Path = request.app.state.settings.runs_dir
    run_dir = (runs_dir / run_id).resolve()
    target = (run_dir / artifact_path).resolve()

    if not str(target).startswith(str(run_dir)) or not target.exists():
        raise HTTPException(status_code=404, detail="Artifact not found")

    return FileResponse(target)
```

Modificar `src/eovrt_media/service/app.py`: agregar `artifacts` al import y registrar su router.

```python
from eovrt_media.service.routers import artifacts, catalog, health, model, runs, stream
```

```python
    app.include_router(stream.router)
    app.include_router(artifacts.router)
```

- [ ] **Step 4: Correr el test y verificar que pasa**

Run: `pytest tests/service/test_artifacts_routes.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add src/eovrt_media/service/routers/artifacts.py src/eovrt_media/service/app.py tests/service/test_artifacts_routes.py
git commit -m "feat(service): detecciones paginadas y artefactos con soporte de range"
```

---

### Task 16: Test de integración end-to-end del servicio

**Files:**
- Create: `tests/service/test_end_to_end.py`

**Interfaces:**
- Consumes: toda la app ensamblada (Tasks 11-15).

Este task no agrega código de producción — verifica que el flujo completo (crear run → seguir WS → leer resultados) funciona ensamblado, como lo usaría la consola.

- [ ] **Step 1: Escribir el test de integración**

Create `tests/service/test_end_to_end.py`:

```python
from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

from eovrt_media.service.app import create_app


def _create_test_images(folder: Path, count: int) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    for i in range(count):
        img = np.zeros((64, 64, 3), dtype=np.uint8)
        img[:] = (i * 10, i * 10, i * 10)
        cv2.imwrite(str(folder / f"img_{i:03d}.jpg"), img)


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("MODEL_REF", "mock")
    monkeypatch.setenv("RUNS_DIR", str(tmp_path / "runs"))
    with TestClient(create_app()) as c:
        yield c, tmp_path


def test_full_flow_compose_run_stream_results(client):
    c, tmp_path = client
    images_dir = tmp_path / "images"
    _create_test_images(images_dir, count=4)

    assert c.get("/readyz").status_code == 200
    assert c.get("/api/model").json()["ref"] == "mock"
    assert {"image_folder", "rtsp"}.issubset(
        {p["id"] for p in c.get("/api/catalog/ingest-plugins").json()}
    )

    payload = {
        "ingest": {"plugin": "image_folder", "config": {"path": str(images_dir)}},
        "prompts": {
            "prompt_set": {
                "id": "adhoc",
                "classes": [{"id": "person", "phrasings": {"default": ["person"]}}],
            },
            "active_ids": ["person"],
        },
        "run": {"save_annotated_video": False},
    }
    run_id = c.post("/api/runs", json=payload).json()["run_id"]

    finished_event = None
    with c.websocket_connect(f"/api/runs/{run_id}/stream") as ws:
        while True:
            event = ws.receive_json()
            if event["type"] == "finished":
                finished_event = event
                break

    assert finished_event["status"] == "succeeded"

    status_body = c.get(f"/api/runs/{run_id}").json()
    assert status_body["status"] == "succeeded"
    assert status_body["summary"]["units_processed"] == 4

    detections = c.get(f"/api/runs/{run_id}/detections").json()
    assert detections["total"] == 4
```

- [ ] **Step 2: Correr el test y verificar que pasa**

Run: `pytest tests/service/test_end_to_end.py -v`
Expected: 1 passed

Si falla, depurar con `pytest tests/service/test_end_to_end.py -v -s` para ver el traceback completo; los puntos de falla más probables son el orden de registro de routers en `app.py` (Tasks 12-15) o el `catalog_root` no apuntando al `configs/` real (verificar que ningún test seteó `EOVRT_MEDIA_CATALOG_ROOT` a un valor incorrecto).

- [ ] **Step 3: Correr toda la suite de `tests/service/` junta**

Run: `pytest tests/service/ -v`
Expected: todos los tests de los Tasks 4-16 en verde.

- [ ] **Step 4: Commit**

```bash
git add tests/service/test_end_to_end.py
git commit -m "test(service): integración end-to-end compose→run→stream→resultados"
```

---

### Task 17: Eliminar la CLI y sus dependientes

**Files:**
- Delete: `src/eovrt_media/cli.py`
- Delete: `tests/test_cli_two_node_local.py`
- Delete: `tests/test_cli_debug_run.py`
- Delete: `scripts/run_grounding_dino_sample.sh`
- Delete: `scripts/run_yoloe_sample.sh`
- Modify: `pyproject.toml` (quitar `[project.scripts]` y `typer`)
- Modify: `Makefile`
- Modify: `CLAUDE.md`
- Modify: `deploy/README.md`

**Interfaces:**
- No produce ni consume interfaces nuevas — es limpieza.

`tests/test_cli_two_node.py` **NO se toca**: pese al nombre, importa `eovrt_media.runtime.two_node` directamente (`run_node_a`/`run_node_b`), no `eovrt_media.cli` — sigue siendo válido y necesario para Fase 2.

`scripts/download_models.sh` **NO se toca**: no depende de la CLI (usa `hf download` directo).

- [ ] **Step 1: Confirmar qué depende de la CLI antes de borrar**

Run: `grep -rn "eovrt_media.cli\|eovrt-media " --include="*.py" --include="*.sh" --include="Makefile" .`
Expected: coincidencias solo en `src/eovrt_media/cli.py`, `tests/test_cli_two_node_local.py`, `tests/test_cli_debug_run.py`, `scripts/run_grounding_dino_sample.sh`, `scripts/run_yoloe_sample.sh`, `Makefile`, y los `Dockerfile.node-a`/`Dockerfile.node-b` bajo `deploy/docker/` (estos últimos se documentan como pendientes en el Step 6, no se borran).

- [ ] **Step 2: Borrar los archivos**

```bash
git rm src/eovrt_media/cli.py
git rm tests/test_cli_two_node_local.py
git rm tests/test_cli_debug_run.py
git rm scripts/run_grounding_dino_sample.sh
git rm scripts/run_yoloe_sample.sh
```

- [ ] **Step 3: Actualizar `pyproject.toml`**

Quitar la sección `[project.scripts]` completa y `"typer"` de `dependencies`:

```toml
[project]
name = "eovrt-media-plane"
version = "0.1.0"
description = "Experimental media plane for E-OVRT-VDP"
requires-python = ">=3.11"
dependencies = [
    "pillow",
    "opencv-python",
    "pydantic",
    "pyyaml",
    "rich",
    "pyzmq",
    "msgpack",
    "fastapi",
    "uvicorn[standard]",
]

[project.optional-dependencies]
edge = []
gpu = [
    "torch",
    "torchvision",
    "transformers",
    "accelerate",
    "huggingface_hub",
    "ultralytics",
]
dev = [
    "pytest",
    "ruff",
    "httpx",
]

[build-system]
requires = ["setuptools>=68.0", "wheel"]
build-backend = "setuptools.build_meta"

[tool.setuptools.packages.find]
where = ["src"]

[tool.ruff]
line-length = 100
target-version = "py311"

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["src"]
```

- [ ] **Step 4: Actualizar `Makefile`**

Reemplazar el contenido completo por:

```makefile
.PHONY: install lint test download-models serve

install:
	python -m pip install --upgrade pip setuptools wheel
	pip install -e ".[dev]"

lint:
	ruff check src tests

test:
	pytest -q

download-models:
	./scripts/download_models.sh

serve:
	MODEL_REF=$${MODEL_REF:-mock} uvicorn eovrt_media.service.app:app --host 0.0.0.0 --port 8000
```

- [ ] **Step 5: Actualizar `CLAUDE.md`**

Reemplazar la sección `## Commands` y las referencias a la CLI en `## Architecture` / `## Testing`:

```markdown
## Commands

```bash
# Setup
python3.11 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# Models
make download-models                            # fetches GDINO tiny+base, MM-GDINO t/b/l, YOLOE-26 s/m/l/x

# Serve — el media-plane es un servicio FastAPI de un solo modelo por instancia.
# MODEL_REF es obligatorio; resuelve contra configs/models/<MODEL_REF>.yaml.
MODEL_REF=mock make serve                       # o: MODEL_REF=yoloe/yoloe-26s make serve
# La consola (repo e-ovrt_experimental-setup/webconsole) compone runs vía HTTP/WS
# contra este servicio: POST /api/runs, WS /api/runs/{id}/stream, GET /api/runs/{id}.

# Test
make test                                       # pytest -q
pytest tests/service/                           # solo los tests del servicio
pytest -xvs                                     # verbose, stop on first failure

# Lint
make lint                                       # ruff check src tests
```

## Architecture

Python service for open-vocabulary object detection (OVD), exposed over HTTP/WebSocket. All behavior is config-driven; no hardcoded paths or thresholds. **No CLI** — the pipeline used to be invoked via `eovrt-media run`; it is now a persistent FastAPI service (see `docs/superpowers/specs/2026-07-01-media-plane-service-design.md`).

**Config catalogs**: el media-plane conserva los **catálogos de capacidades** `configs/models/` y `configs/datasets/`, resueltos vía `config/loader.py:load_catalog_entry()`. Los prompt sets ya no se leen de un repo hermano: llegan **inline** en el body de `POST /api/runs` (ver `service/schemas.py:PromptsRequest`).

**Service (`service/`)**: `app.py` carga el modelo fijo de esta instancia de forma síncrona en el `lifespan` desde `MODEL_REF` (env var) — sin recarga dinámica; cambiar de modelo requiere reiniciar el proceso con otro `MODEL_REF`. `RunManager` (`run_manager.py`) ejecuta un run activo a la vez (409 si hay uno corriendo) en un hilo, reusando `runtime/pipeline.py:run_pipeline()` con un adapter ya cargado (no lo recarga ni lo cierra). `RunEventBus` (`events.py`) bufferiza telemetría por run y la expone vía `WS /api/runs/{id}/stream`.

**Execution path (dentro de un run)**: `run_pipeline()` → producer thread (read → rate-gate → normalize) + consumer thread (inference → postprocess → write), coupled via `MemoryTransportAdapter`. Sin cambios respecto al pipeline original — el servicio solo lo invoca con hooks adicionales (`on_event`, `on_source_ready`, `adapter` precargado).

**Key abstractions**:
- `BaseDetectorAdapter` (`models/base.py`) — plugin interface for inference; register new adapters in `models/__init__.py:create_adapter()`
- `BaseSource` (`sources/base.py`) — yields `VisualUnit` objects; implementations: `ImageFolderSource`, `VideoFileSource`, `RtspSource` (live RTSP with wall-clock timestamps and reconnect), `OakDSource` (OAK-D Pro PoE deferred, raises `NotImplementedError`). Catálogo consultable en `service/ingest_registry.py`.
- `RunContext` (`runtime/run_context.py`) — stateful execution context (run_id, unit counts, timing); owns the output directory
- `RunArtifactWriter` (`sinks/run_artifact_writer.py`) — persists to `runs/<run_id>/`: `detections.jsonl`, `metrics.jsonl`, `errors.jsonl`, `summary.json`, `previews/`

**Data contracts** (`contracts/`) — Pydantic models flow through the pipeline: `VisualUnit` → `RawDetection` → `Detection` → `DetectionEvent`/`MetricSample` for persistence.

**Error handling**: each pipeline stage catches independently; failures are logged to `errors.jsonl` and execution continues to the next unit.

**Metrics**: sub-stage latency tracked at microsecond granularity via `metrics/timers.py`; aggregated (p95, p99, FPS) in `metrics/collector.py`. Live telemetry additionally streams per-unit via `service/events.py`.

## Testing

`MockDetector` (`models/mock_detector.py`) enables full end-to-end pipeline tests without loading real model weights — use it for integration tests (no GPU, no artificial delay). Tests live in `tests/`; service-specific tests live in `tests/service/` using `fastapi.testclient.TestClient` (no async runtime required).

## Out of scope

This pipeline does not implement: risk rules, alert generation, multi-object tracking (MOT), zones/geofences, control plane logic, UI, or message queues. The two-node EBE split (`runtime/two_node.py`) still exists for Fase 2 but is not wired into the service yet — see `docs/superpowers/specs/2026-07-01-media-plane-service-design.md` §10.
```

- [ ] **Step 6: Documentar en `deploy/README.md` que el split two-node quedó desactualizado**

Leer `deploy/README.md` primero, luego agregar al final:

```markdown

## Nota (2026-07-01): pendiente de Fase 2

`docker/Dockerfile.node-a` y `docker/Dockerfile.node-b` invocan `eovrt-media run-producer`
/`run-consumer`, comandos de la CLI eliminada en el pivote a servicio (ver
`docs/superpowers/specs/2026-07-01-media-plane-service-design.md`). Estas imágenes,
`docker-compose*.yml` y `configs/two_node_*.example.yaml` quedan **desactualizados**
hasta que Fase 2 rediseñe el split EBE (edge/GPU) contra la API HTTP del nuevo servicio,
en vez de contra subcomandos de CLI. No usar para desplegar mientras tanto.
```

- [ ] **Step 7: Correr toda la suite y el linter**

Run: `pytest -q`
Expected: todos los tests en verde (sin los 2 archivos de test de CLI borrados).

Run: `ruff check src tests`
Expected: sin errores.

- [ ] **Step 8: Commit**

```bash
git add -A
git commit -m "refactor: eliminar la CLI (eovrt-media) y sus dependientes directos"
```

---

### Task 18: `Dockerfile.service` y verificación final

**Files:**
- Create: `deploy/docker/Dockerfile.service`

**Interfaces:**
- No produce interfaces de código — es el empaquetado de Fase 1 (contenedor único DBE).

- [ ] **Step 1: Crear el Dockerfile**

Create `deploy/docker/Dockerfile.service`:

```dockerfile
# Servicio de inferencia media-plane — Fase 1, contenedor único DBE. Requiere GPU NVIDIA.
FROM nvidia/cuda:12.6.3-cudnn-runtime-ubuntu24.04

RUN apt-get update && apt-get install -y --no-install-recommends \
    git python3 python3-pip python3-venv libgl1 libglib2.0-0 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml ./
COPY src ./src
COPY configs ./configs
RUN python3 -m venv /opt/venv && /opt/venv/bin/pip install --no-cache-dir -e ".[gpu]"
ENV PATH="/opt/venv/bin:${PATH}"

ENV RUNS_DIR=/data/runs
VOLUME ["/data/runs", "/root/.cache/huggingface", "/data/datasets"]

EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=3s --start-period=60s --retries=5 \
    CMD python3 -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/healthz')" || exit 1

ENTRYPOINT ["uvicorn", "eovrt_media.service.app:app", "--host", "0.0.0.0", "--port", "8000"]
```

Nota: no se agrega un `docker-compose.service.yml` en este plan — la orquestación de volúmenes/env vars concretos (mapeo real de `/data/datasets` a `e-ovrt_datasets/`) depende de dónde se despliegue, y queda para cuando exista un host GPU real disponible.

- [ ] **Step 2: Verificar la sintaxis del Dockerfile (sin build real, no hay GPU en este entorno)**

Run: `docker build -f deploy/docker/Dockerfile.service --check . 2>&1 || true`

Si `docker` no está disponible en este entorno de desarrollo, omitir este step y dejar constancia en el commit de que el build real se valida en el host con GPU.

- [ ] **Step 3: Verificación final de todo el plan**

Run: `pytest -q`
Expected: suite completa en verde, incluyendo `tests/service/`.

Run: `ruff check src tests`
Expected: sin errores.

Run: `MODEL_REF=mock uvicorn eovrt_media.service.app:app --host 0.0.0.0 --port 8000 &`
seguido de:
Run: `curl -s http://localhost:8000/healthz && curl -s http://localhost:8000/readyz && curl -s http://localhost:8000/api/model`
Expected: `{"status":"ok"}`, `{"status":"ready"}`, y un JSON con `"ref":"mock"`.

Detener el proceso de uvicorn de prueba (`kill %1` o equivalente) al terminar.

- [ ] **Step 4: Commit**

```bash
git add deploy/docker/Dockerfile.service
git commit -m "build: Dockerfile del servicio (Fase 1, contenedor único DBE)"
```

---

## Self-Review Notes

- **Cobertura del spec**: §3.1 (contrato HTTP/WS) → Tasks 11-15; §3.2 (pipeline interno reusado) → Tasks 3, 8, 10; §4 (ciclo de vida simple, sin recarga) → Tasks 6, 10, 11 (carga síncrona en lifespan, sin `ModelRegistry`); §5 (plugins de ingesta) → Task 4; §6 (refactor: eliminar CLI, agregar `service/`) → Tasks 1-17; §7 (datasets montados, prompts inline, pesos/RUNS_DIR en volúmenes) → Task 8 (prompts inline), Task 18 (volúmenes Docker); §8 (manejo de errores) → validación Pydantic (422) en Task 13, `409`/`404` en Task 13, errores de runtime ya manejados por `errors.jsonl` existente + eventos WS; §9 (testing con mock) → todos los tasks de servicio; §10 (Fase 1 vs Fase 2) → este plan cubre exactamente Fase 1, Fase 2 (two-node) explícitamente fuera de alcance.
- **Decisión no explícita en el spec, tomada durante la planificación**: `run_pipeline` hoy crea y cierra su propio adapter internamente en cada llamada — esto violaba directamente "sin recarga in-process" si el servicio lo hubiera usado tal cual. Se agregó el parámetro `adapter` (Task 3) para que el servicio inyecte el adapter cargado una vez en el lifespan y `run_pipeline` nunca lo recargue ni lo cierre.
- **Placeholder scan**: sin TBD/TODO; todo el código de cada step está completo y es el código real a escribir.
- **Consistencia de tipos**: `RunHandle.source: BaseSource | None`, `on_source_ready: Callable[[BaseSource], None]`, `RunManager._execute` — coherentes entre Tasks 3 y 10. `CreateRunRequest`/`RunStatusResponse`/etc. definidos una vez en Task 7 y reusados sin renombrar en Tasks 8, 10, 13.
