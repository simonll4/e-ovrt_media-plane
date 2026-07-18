# Media-Plane Service (Fase 1) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Convertir el media-plane de CLI batch a servicio de inferencia persistente (FastAPI, HTTP/WS), Fase 1 del spec `docs/superpowers/specs/2026-07-01-media-plane-service-design.md`.

**Architecture:** Un paquete nuevo `service/` (FastAPI app + RunManager de un run activo) que envuelve el pipeline existente descompuesto: el modelo se carga **una vez al startup** desde `EOVRT_MODEL_REF` y `execute_run()` recibe el adapter ya cargado. La telemetría fluye por un event sink in-process (decorando `RunArtifactWriter`) hacia WebSocket con coalescing. El CLI se elimina; los utilitarios migran a `eovrt_media.tools`.

**Tech Stack:** Python 3.11, FastAPI ≥0.110 (Starlette ≥0.36 para Range), uvicorn, Pydantic v2, pytest + httpx TestClient, MockDetector para todos los tests.

## Global Constraints

- Python `>=3.11`; Pydantic v2; ruff `line-length = 100` (`make lint` debe pasar al final de cada task).
- `pytest -q` completo debe pasar al final de cada task (291 tests existentes + los nuevos). MockDetector para todo test nuevo — **nunca** cargar pesos reales ni requerir GPU en tests.
- Todo config-driven: cero rutas/thresholds hardcodeados; variables de entorno namespaced `EOVRT_*` (el spec dice `MODEL_REF` genérico; el nombre canónico implementado es `EOVRT_MODEL_REF`).
- Contrato canónico del run request (Spec A §3.1, nombres EXACTOS): `{ ingest: {plugin, config}, prompts: {set_inline, active_ids}, run: {stride, max_units, save_annotated_video, ...} }`. La sección `model` en el request → `422`.
- Sin recarga de modelo in-process. Un run activo a la vez (`409` si ocupado).
- No romper `run_node_a`/`run_node_b` (`runtime/two_node.py`) ni los tests existentes: `run_pipeline(config, console)` se conserva como wrapper con la misma firma.
- **Regla del workspace (projects/CLAUDE.md):** los pasos de commit de este plan se ejecutan SOLO si el usuario habilitó commits explícitamente para la sesión de ejecución. Si no, dejar los cambios en el working tree y reportar qué se habría commiteado.
- Repo: `/home/simonll4/projects/e-ovrt_media-plane`. Todos los paths de abajo son relativos a esa raíz. Correr pytest desde la raíz del repo.

## File Structure (resultado final)

```
src/eovrt_media/service/
├── __init__.py
├── settings.py         # ServiceSettings desde env
├── app.py              # create_app() + lifespan (carga de modelo, GC, shutdown)
├── events.py           # RunEventSink, EventEmittingArtifactWriter, EventBroadcaster/Subscriber
├── run_request.py      # RunRequest (contrato canónico) + to_raw_run_config()
├── run_manager.py      # RunManager (un run activo, stop, watchdog, finalize)
├── retention.py        # gc_runs_dir()
└── routers/
    ├── __init__.py
    ├── health.py       # /healthz /readyz
    ├── model.py        # GET /api/model
    ├── catalog.py      # GET /api/catalog/{ingest-plugins,datasets}
    ├── runs.py         # POST/GET/DELETE /api/runs, stop, detections, artifacts
    └── stream.py       # WS /api/runs/{id}/stream
src/eovrt_media/sources/registry.py     # registro de plugins de ingesta
src/eovrt_media/tools/                  # evaluate / inspect_runs / debug_run (ex-CLI)
```

Modificados: `config/loader.py` (dict-based + `resolve_model_ref` + datasets root), `config/schemas.py` (`set_inline`, redacción), `transport/memory.py` (close no bloqueante), `runtime/pipeline.py` (descomposición `execute_run` + `RunControl`), `pyproject.toml`, `Makefile`, `CLAUDE.md`. Eliminados: `cli.py`, `runtime/two_node_local.py`, `tests/test_cli_two_node_local.py`, `scripts/run_grounding_dino_sample.sh`, `scripts/run_yoloe_sample.sh`.

---

### Task 1: Dependencias + ServiceSettings + app esqueleto con health

**Files:**
- Modify: `pyproject.toml`
- Create: `src/eovrt_media/service/__init__.py`, `src/eovrt_media/service/settings.py`, `src/eovrt_media/service/app.py`, `src/eovrt_media/service/routers/__init__.py`, `src/eovrt_media/service/routers/health.py`
- Test: `tests/test_service_settings.py`, `tests/test_service_health.py`

**Interfaces:**
- Produces: `ServiceSettings.from_env(env: Mapping[str,str] | None) -> ServiceSettings` (campos: `model_ref: str`, `model_device: str | None`, `runs_dir: Path`, `datasets_root: Path | None`, `catalog_root: Path | None`, `watchdog_seconds: float`, `retention_max_age_days: float | None`, `retention_max_total_gb: float | None`, `shutdown_grace_seconds: float`); `create_app(settings: ServiceSettings | None = None) -> FastAPI` con `app.state.settings/ready/load_error`.

- [ ] **Step 1: Agregar dependencias del servicio**

En `pyproject.toml`, `[project].dependencies` agrega `"fastapi>=0.110"` y `"uvicorn[standard]"`; en `dev` agrega `"httpx"`. Luego `pip install -e ".[dev]"`.

- [ ] **Step 2: Tests que fallan**

```python
# tests/test_service_settings.py
from pathlib import Path
import pytest
from eovrt_media.service.settings import ServiceSettings


def test_from_env_minimo():
    s = ServiceSettings.from_env({"EOVRT_MODEL_REF": "mock"})
    assert s.model_ref == "mock"
    assert s.runs_dir == Path("runs")
    assert s.datasets_root is None
    assert s.watchdog_seconds == 120.0


def test_from_env_completo():
    s = ServiceSettings.from_env({
        "EOVRT_MODEL_REF": "grounding-dino/gdino-tiny",
        "EOVRT_MODEL_DEVICE": "cuda",
        "EOVRT_RUNS_DIR": "/data/runs",
        "EOVRT_DATASETS_ROOT": "/data/datasets",
        "EOVRT_WATCHDOG_SECONDS": "30",
        "EOVRT_RUNS_MAX_AGE_DAYS": "7",
    })
    assert s.model_device == "cuda"
    assert s.datasets_root == Path("/data/datasets")
    assert s.retention_max_age_days == 7.0


def test_model_ref_obligatorio():
    with pytest.raises(ValueError, match="EOVRT_MODEL_REF"):
        ServiceSettings.from_env({})
```

```python
# tests/test_service_health.py
from fastapi.testclient import TestClient
from eovrt_media.service.app import create_app
from eovrt_media.service.settings import ServiceSettings


def _app():
    return create_app(ServiceSettings.from_env({"EOVRT_MODEL_REF": "mock"}))


def test_healthz_ok():
    with TestClient(_app()) as client:
        r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_readyz_503_sin_modelo():
    # En esta task el lifespan aún no carga modelo: not ready.
    # (Task 11 reemplaza este test por la variante con carga real.)
    with TestClient(_app()) as client:
        r = client.get("/readyz")
    assert r.status_code == 503
```

- [ ] **Step 3: Verificar que fallan**

Run: `pytest tests/test_service_settings.py tests/test_service_health.py -q`
Expected: FAIL / ERROR con `ModuleNotFoundError: eovrt_media.service`

- [ ] **Step 4: Implementación**

```python
# src/eovrt_media/service/__init__.py
"""Servicio de inferencia del media-plane (Spec A, Fase 1)."""
```

```python
# src/eovrt_media/service/settings.py
"""Configuración del servicio desde variables de entorno EOVRT_*."""
from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ServiceSettings:
    model_ref: str
    model_device: str | None
    runs_dir: Path
    datasets_root: Path | None
    catalog_root: Path | None
    watchdog_seconds: float
    retention_max_age_days: float | None
    retention_max_total_gb: float | None
    shutdown_grace_seconds: float

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> ServiceSettings:
        env = os.environ if env is None else env
        model_ref = env.get("EOVRT_MODEL_REF")
        if not model_ref:
            raise ValueError(
                "EOVRT_MODEL_REF es obligatorio (p.ej. 'mock' o 'grounding-dino/gdino-tiny')"
            )

        def _path(key: str) -> Path | None:
            value = env.get(key)
            return Path(value) if value else None

        def _float(key: str) -> float | None:
            value = env.get(key)
            return float(value) if value else None

        return cls(
            model_ref=model_ref,
            model_device=env.get("EOVRT_MODEL_DEVICE") or None,
            runs_dir=Path(env.get("EOVRT_RUNS_DIR", "runs")),
            datasets_root=_path("EOVRT_DATASETS_ROOT"),
            catalog_root=_path("EOVRT_MEDIA_CATALOG_ROOT"),
            watchdog_seconds=float(env.get("EOVRT_WATCHDOG_SECONDS", "120")),
            retention_max_age_days=_float("EOVRT_RUNS_MAX_AGE_DAYS"),
            retention_max_total_gb=_float("EOVRT_RUNS_MAX_TOTAL_GB"),
            shutdown_grace_seconds=float(env.get("EOVRT_SHUTDOWN_GRACE_SECONDS", "20")),
        )
```

```python
# src/eovrt_media/service/routers/__init__.py
```

```python
# src/eovrt_media/service/routers/health.py
"""Endpoints de liveness/readiness para el contenedor."""
from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

router = APIRouter()


@router.get("/healthz")
def healthz() -> dict:
    return {"status": "ok"}


@router.get("/readyz")
def readyz(request: Request):
    if getattr(request.app.state, "ready", False):
        model = getattr(request.app.state, "model_section", None)
        return {"status": "ready", "model": model.ref if model else None}
    return JSONResponse(
        status_code=503,
        content={"status": "not_ready", "error": getattr(request.app.state, "load_error", None)},
    )
```

```python
# src/eovrt_media/service/app.py
"""Factory de la app FastAPI del servicio media-plane."""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from eovrt_media.service.routers import health
from eovrt_media.service.settings import ServiceSettings


@asynccontextmanager
async def _lifespan(app: FastAPI):
    # Task 11 agrega acá: carga de modelo, RunManager, GC y shutdown limpio.
    yield


def create_app(settings: ServiceSettings | None = None) -> FastAPI:
    settings = settings or ServiceSettings.from_env()
    app = FastAPI(title="eovrt-media-plane", lifespan=_lifespan)
    app.state.settings = settings
    app.state.ready = False
    app.state.load_error = None
    app.include_router(health.router)
    return app
```

- [ ] **Step 5: Verificar que pasan + suite completa**

Run: `pytest tests/test_service_settings.py tests/test_service_health.py -q && pytest -q && make lint`
Expected: PASS todo.

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml src/eovrt_media/service tests/test_service_settings.py tests/test_service_health.py
git commit -m "feat(service): settings desde env y app FastAPI con healthz/readyz"
```

---

### Task 2: Loader dict-based + `resolve_model_ref`

**Files:**
- Modify: `src/eovrt_media/config/loader.py` (factorizar `load_run_config`)
- Test: `tests/test_loader_data.py`

**Interfaces:**
- Consumes: `find_plane_catalog_root`, `_load_catalog_entry`, `_resolve_section_ref`, `_derive_defaults`, `_validate_deployment`, `load_prompts_file` (existentes en `loader.py`).
- Produces: `load_run_config_data(raw: dict, *, plane_root: Path, experiment_root: Path | None = None, datasets_root: Path | None = None, config_path: Path | None = None) -> RunConfig`; `resolve_model_ref(ref: str, catalog_root: str | Path | None = None) -> ModelSection`. `load_run_config(config_path, catalog_root)` conserva firma y comportamiento (delega).

- [ ] **Step 1: Test que falla**

```python
# tests/test_loader_data.py
from pathlib import Path
import pytest
from eovrt_media.config.loader import (
    find_plane_catalog_root,
    load_run_config_data,
    resolve_model_ref,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
PLANE_ROOT = REPO_ROOT / "configs"
FIXTURE_PROMPTS = REPO_ROOT / "tests" / "fixtures"  # contiene prompts/ (fixtures existentes)


def _raw(tmp_path):
    return {
        "run": {"scenario": "DBE"},
        "source": {"type": "image_folder", "path": str(tmp_path)},
        "model": {"adapter": "mock"},
        "prompts": {"ref": "prompts_smoke"},  # tests/fixtures/prompts/prompts_smoke.yaml
    }


def test_load_run_config_data_valida_dict(tmp_path):
    config = load_run_config_data(
        _raw(tmp_path), plane_root=PLANE_ROOT, experiment_root=FIXTURE_PROMPTS
    )
    assert config.model.adapter == "mock"
    assert config.prompts_file is not None
    assert config.rate_control.policy == "deterministic"  # default derivado


def test_load_run_config_data_rechaza_sampling(tmp_path):
    raw = _raw(tmp_path)
    raw["sampling"] = {"every_n": 2}
    with pytest.raises(ValueError, match="sampling"):
        load_run_config_data(raw, plane_root=PLANE_ROOT, experiment_root=FIXTURE_PROMPTS)


def test_resolve_model_ref_mock():
    section = resolve_model_ref("mock")
    assert section.ref == "mock"
    assert (section.adapter or section.name) == "mock"


def test_resolve_model_ref_inexistente():
    with pytest.raises(FileNotFoundError):
        resolve_model_ref("no-existe/nada")
```

Nota: si el nombre real del fixture de prompts difiere (`ls tests/fixtures/prompts/`), usar el que exista.

- [ ] **Step 2: Verificar que falla**

Run: `pytest tests/test_loader_data.py -q`
Expected: FAIL con `ImportError: cannot import name 'load_run_config_data'`

- [ ] **Step 3: Implementación**

En `loader.py`, mover el cuerpo de `load_run_config` posterior a la lectura del YAML a la nueva función, y dejar `load_run_config` como wrapper:

```python
def resolve_model_ref(ref: str, catalog_root: str | Path | None = None) -> "ModelSection":
    """Resuelve un MODEL_REF contra configs/models/ → ModelSection (para el servicio)."""
    from eovrt_media.config.schemas import ModelSection

    plane_root = find_plane_catalog_root(None, catalog_root)
    base = _load_catalog_entry(plane_root, "models", ref)
    return ModelSection(**{**base, "ref": ref})


def load_run_config_data(
    raw: dict[str, Any],
    *,
    plane_root: Path,
    experiment_root: Path | None = None,
    datasets_root: Path | None = None,  # se usa en Task 4
    config_path: Path | None = None,
) -> RunConfig:
    """Valida una run config desde un dict ya parseado (API del servicio o archivo)."""
    if not isinstance(raw, dict):
        raise ValueError("Configuración inválida (se esperaba mapping)")
    if "sampling" in raw:
        _raise_sampling_migration_error()

    _resolve_section_ref(raw, "model", "models", plane_root)
    _resolve_section_ref(raw, "source", "datasets", plane_root)
    _derive_defaults(raw)

    prompts_data = raw.get("prompts")
    if (
        isinstance(prompts_data, dict)
        and prompts_data.get("ref")
        and not prompts_data.get("file")
        and not prompts_data.get("set_inline")  # Task 3
    ):
        ref = prompts_data["ref"]
        roots = [experiment_root] if experiment_root is not None else []
        roots.append(plane_root)
        for root in roots:
            candidate = root / "prompts" / f"{ref}.yaml"
            if candidate.exists():
                break
        prompts_data["file"] = str(candidate)

    config = RunConfig(**raw)
    config.config_path = config_path

    if config.prompts.file:
        prompts_path = Path(config.prompts.file)
        if not prompts_path.is_absolute() and config_path is not None:
            relative_to_config = config_path.parent / prompts_path
            if relative_to_config.exists():
                prompts_path = relative_to_config
        config.prompts_file = load_prompts_file(prompts_path)

    _validate_deployment(config)
    return config


def load_run_config(
    config_path: Path, catalog_root: str | Path | None = None
) -> RunConfig:
    """Carga una run config desde archivo YAML (docstring existente se conserva)."""
    config_path = Path(config_path)
    if not config_path.exists():
        raise FileNotFoundError(f"Archivo de configuración no encontrado: {config_path}")
    with open(config_path) as f:
        raw = yaml.safe_load(f) or {}
    return load_run_config_data(
        raw,
        plane_root=find_plane_catalog_root(config_path, catalog_root),
        experiment_root=find_experiment_root(config_path),
        config_path=config_path,
    )
```

(El condicional `if config.prompts.file:` reemplaza la carga incondicional; con `ref` ya resuelto a `file` el comportamiento actual se preserva. Task 3 agrega la rama `set_inline`.)

- [ ] **Step 4: Verificar + suite completa**

Run: `pytest tests/test_loader_data.py -q && pytest -q`
Expected: PASS todo (los tests existentes de loader cubren la no-regresión del wrapper).

- [ ] **Step 5: Commit**

```bash
git add src/eovrt_media/config/loader.py tests/test_loader_data.py
git commit -m "refactor(config): loader dict-based (load_run_config_data) + resolve_model_ref"
```

---

### Task 3: Prompts inline (`set_inline`)

**Files:**
- Modify: `src/eovrt_media/config/schemas.py` (`PromptsSection`), `src/eovrt_media/config/loader.py` (rama inline)
- Test: `tests/test_prompts_inline.py`

**Interfaces:**
- Produces: `PromptsSection.set_inline: PromptSet | None` (acepta dict validado a `PromptSet`); precedencia `set_inline > file > ref`; `load_run_config_data` construye `config.prompts_file` desde el inline.

- [ ] **Step 1: Test que falla**

```python
# tests/test_prompts_inline.py
from pathlib import Path
import pytest
from eovrt_media.config.loader import load_run_config_data
from eovrt_media.config.schemas import PromptsSection

REPO_ROOT = Path(__file__).resolve().parents[1]
PLANE_ROOT = REPO_ROOT / "configs"

SET_INLINE = {
    "id": "inline_test",
    "classes": [
        {"id": "person", "phrasings": {"default": ["person"]}},
        {"id": "helmet", "phrasings": {"default": ["helmet"]}},
    ],
}


def test_prompts_section_acepta_set_inline():
    section = PromptsSection(set_inline=SET_INLINE)
    assert section.set_inline.id == "inline_test"


def test_prompts_section_requiere_alguna_fuente():
    with pytest.raises(ValueError, match="ref.*file.*set_inline|set_inline"):
        PromptsSection()


def test_run_config_con_prompts_inline(tmp_path):
    raw = {
        "run": {"scenario": "DBE"},
        "source": {"type": "image_folder", "path": str(tmp_path)},
        "model": {"adapter": "mock"},
        "prompts": {"set_inline": SET_INLINE, "active_ids": ["person"]},
    }
    config = load_run_config_data(raw, plane_root=PLANE_ROOT)
    assert config.prompts_file.resolved_set_id() == "inline_test"
    plan = config.build_prompt_plan("default")
    assert [p.prompt_id for p in plan.phrases] == ["person"]
```

- [ ] **Step 2: Verificar que falla**

Run: `pytest tests/test_prompts_inline.py -q`
Expected: FAIL con `ValidationError` (campo `set_inline` desconocido) o `ValueError` del validador actual.

- [ ] **Step 3: Implementación**

En `schemas.py`, `PromptsSection`:

```python
class PromptsSection(BaseModel):
    """Sección 'prompts' de la configuración.

    Acepta ``ref`` (catálogo/experimento), ``file`` (ruta explícita) o
    ``set_inline`` (PromptSet embebido — contrato del servicio, Spec A §3.1).
    Precedencia: set_inline > file > ref.
    """

    ref: str | None = None
    file: str | None = None
    set_inline: PromptSet | None = None
    active_ids: list[str] | None = None

    @model_validator(mode="after")
    def require_prompt_source(self) -> PromptsSection:
        if self.ref is None and self.file is None and self.set_inline is None:
            raise ValueError("La sección 'prompts' requiere 'ref', 'file' o 'set_inline'")
        return self
```

En `loader.py`, en `load_run_config_data`, reemplazar el bloque `if config.prompts.file:` por:

```python
    if config.prompts.set_inline is not None:
        config.prompts_file = PromptsFile(prompt_set=config.prompts.set_inline)
    elif config.prompts.file:
        prompts_path = Path(config.prompts.file)
        if not prompts_path.is_absolute() and config_path is not None:
            relative_to_config = config_path.parent / prompts_path
            if relative_to_config.exists():
                prompts_path = relative_to_config
        config.prompts_file = load_prompts_file(prompts_path)
```

- [ ] **Step 4: Verificar + suite completa**

Run: `pytest tests/test_prompts_inline.py -q && pytest -q`
Expected: PASS todo.

- [ ] **Step 5: Commit**

```bash
git add src/eovrt_media/config/schemas.py src/eovrt_media/config/loader.py tests/test_prompts_inline.py
git commit -m "feat(config): prompts set_inline en PromptsSection y loader"
```

---

### Task 4: Datasets container-aware (`EOVRT_DATASETS_ROOT`)

**Files:**
- Modify: `src/eovrt_media/config/loader.py`
- Test: `tests/test_datasets_root.py`

**Interfaces:**
- Produces: `rebase_dataset_path(path: str, datasets_root: Path | None) -> str` (público, lo reusa el catálogo en Task 15); `load_run_config_data` aplica el rebase a `source.path` tras resolver el ref; si `datasets_root` es None toma `EOVRT_DATASETS_ROOT` del entorno.

- [ ] **Step 1: Test que falla**

```python
# tests/test_datasets_root.py
from pathlib import Path
from eovrt_media.config.loader import load_run_config_data, rebase_dataset_path

REPO_ROOT = Path(__file__).resolve().parents[1]
PLANE_ROOT = REPO_ROOT / "configs"

SET_INLINE = {"id": "t", "classes": [{"id": "p", "phrasings": {"default": ["p"]}}]}


def test_rebase_con_root():
    assert rebase_dataset_path(
        "../e-ovrt_datasets/datasets/raw/chv/images", Path("/data/datasets")
    ) == "/data/datasets/datasets/raw/chv/images"


def test_rebase_sin_root_es_identidad():
    p = "../e-ovrt_datasets/datasets/raw/chv/images"
    assert rebase_dataset_path(p, None) == p


def test_rebase_no_toca_paths_ajenos():
    assert rebase_dataset_path("/abs/video.mp4", Path("/data/datasets")) == "/abs/video.mp4"


def test_load_run_config_data_rebasa_source_path():
    raw = {
        "run": {"scenario": "DBE"},
        "source": {"type": "image_folder", "path": "../e-ovrt_datasets/datasets/raw/x"},
        "model": {"adapter": "mock"},
        "prompts": {"set_inline": SET_INLINE},
    }
    config = load_run_config_data(
        raw, plane_root=PLANE_ROOT, datasets_root=Path("/mnt/ds")
    )
    assert config.source.path == "/mnt/ds/datasets/raw/x"
```

- [ ] **Step 2: Verificar que falla**

Run: `pytest tests/test_datasets_root.py -q`
Expected: FAIL con `ImportError: rebase_dataset_path`

- [ ] **Step 3: Implementación**

En `loader.py`:

```python
_DATASETS_SIBLING_PREFIX = "../e-ovrt_datasets/"


def rebase_dataset_path(path: str, datasets_root: Path | None) -> str:
    """Rebasa rutas relativas al repo hermano de datasets sobre un root montado.

    Los ``configs/datasets/*.yaml`` usan ``../e-ovrt_datasets/...`` (resuelto
    contra CWD). En contenedor los datasets se montan en EOVRT_DATASETS_ROOT.
    """
    if datasets_root is None or not path.startswith(_DATASETS_SIBLING_PREFIX):
        return path
    return str(datasets_root / path[len(_DATASETS_SIBLING_PREFIX):])
```

En `load_run_config_data`, después de `_resolve_section_ref(raw, "source", ...)` y antes de `_derive_defaults(raw)`:

```python
    if datasets_root is None:
        env_root = os.environ.get("EOVRT_DATASETS_ROOT")
        datasets_root = Path(env_root) if env_root else None
    source_data = raw.get("source")
    if isinstance(source_data, dict) and isinstance(source_data.get("path"), str):
        source_data["path"] = rebase_dataset_path(source_data["path"], datasets_root)
```

- [ ] **Step 4: Verificar + suite completa**

Run: `pytest tests/test_datasets_root.py -q && pytest -q`
Expected: PASS todo.

- [ ] **Step 5: Commit**

```bash
git add src/eovrt_media/config/loader.py tests/test_datasets_root.py
git commit -m "feat(config): rebase de datasets por EOVRT_DATASETS_ROOT (contenedor)"
```

---

### Task 5: `RunRequest` canónico → run config

**Files:**
- Create: `src/eovrt_media/service/run_request.py`
- Test: `tests/test_run_request.py`

**Interfaces:**
- Consumes: `ModelSection` (schemas), contrato canónico Spec A §3.1.
- Produces: `RunRequest` (Pydantic, `extra="forbid"` en todos los niveles: `ingest: IngestSpec{plugin: str, config: dict}`, `prompts: PromptsSpec{set_inline: dict, active_ids: list[str] | None}`, `run: RunParams{stride, max_units, save_annotated_video, save_previews, name}`); `to_raw_run_config(request: RunRequest, model_section: ModelSection) -> dict` (el modelo viene SIEMPRE de la instancia).

- [ ] **Step 1: Test que falla**

```python
# tests/test_run_request.py
import pytest
from pydantic import ValidationError
from eovrt_media.config.loader import resolve_model_ref
from eovrt_media.service.run_request import RunRequest, to_raw_run_config

SET_INLINE = {"id": "t", "classes": [{"id": "p", "phrasings": {"default": ["p"]}}]}


def _request(**overrides):
    body = {
        "ingest": {"plugin": "image_folder", "config": {"path": "/tmp/imgs"}},
        "prompts": {"set_inline": SET_INLINE, "active_ids": ["p"]},
        "run": {"stride": 2, "max_units": 10, "save_annotated_video": True},
    }
    body.update(overrides)
    return body


def test_request_valido():
    req = RunRequest(**_request())
    assert req.ingest.plugin == "image_folder"
    assert req.run.stride == 2


def test_seccion_model_rechazada():
    with pytest.raises(ValidationError):
        RunRequest(**_request(model={"ref": "yoloe/yoloe-26s"}))


def test_to_raw_run_config_mapea_contrato():
    raw = to_raw_run_config(RunRequest(**_request()), resolve_model_ref("mock"))
    assert raw["source"]["type"] == "image_folder"
    assert raw["source"]["path"] == "/tmp/imgs"
    assert raw["rate_control"]["stride"] == 2          # run.stride → rate_control.stride
    assert raw["run"]["max_units"] == 10
    assert raw["outputs"]["save_annotated_video"] is True
    assert raw["prompts"]["set_inline"]["id"] == "t"
    assert raw["model"]["adapter"] == "mock"           # modelo de la instancia, no del request


def test_ingest_config_dataset_ref():
    body = _request(ingest={"plugin": "image_folder", "config": {"dataset": "demo_v2"}})
    raw = to_raw_run_config(RunRequest(**body), resolve_model_ref("mock"))
    assert raw["source"] == {"ref": "demo_v2"}
```

- [ ] **Step 2: Verificar que falla**

Run: `pytest tests/test_run_request.py -q`
Expected: FAIL con `ModuleNotFoundError`

- [ ] **Step 3: Implementación**

```python
# src/eovrt_media/service/run_request.py
"""Contrato canónico del run request (Spec A §3.1) y su traducción a run config."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from eovrt_media.config.schemas import ModelSection

_PLUGIN_TO_SOURCE_TYPE = {
    "image_folder": "image_folder",
    "video_file": "video_file",
    "rtsp": "rtsp",
    "oak_d": "oak_d",
}


class IngestSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    plugin: str
    config: dict[str, Any] = Field(default_factory=dict)


class PromptsSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    set_inline: dict[str, Any]
    active_ids: list[str] | None = None


class RunParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    stride: int | None = None
    max_units: int | None = None
    save_annotated_video: bool = False
    save_previews: bool = True
    name: str | None = None


class RunRequest(BaseModel):
    # extra="forbid": una sección 'model' (u otra desconocida) en el body → 422.
    model_config = ConfigDict(extra="forbid")
    ingest: IngestSpec
    prompts: PromptsSpec
    run: RunParams = Field(default_factory=RunParams)


def to_raw_run_config(request: RunRequest, model_section: ModelSection) -> dict[str, Any]:
    """Traduce el request canónico al dict de run config del loader.

    El modelo NUNCA viene del request: es el que la instancia cargó al startup.
    """
    if request.ingest.plugin not in _PLUGIN_TO_SOURCE_TYPE:
        raise ValueError(
            f"Plugin de ingesta desconocido: {request.ingest.plugin!r}. "
            f"Disponibles: {sorted(_PLUGIN_TO_SOURCE_TYPE)}"
        )
    ingest_config = dict(request.ingest.config)
    dataset = ingest_config.pop("dataset", None)
    if dataset:
        source: dict[str, Any] = {"ref": dataset, **ingest_config}
    else:
        source = {"type": _PLUGIN_TO_SOURCE_TYPE[request.ingest.plugin], **ingest_config}

    raw: dict[str, Any] = {
        "run": {"name": request.run.name, "max_units": request.run.max_units},
        "source": source,
        "model": model_section.model_dump(exclude_none=True),
        "prompts": {
            "set_inline": request.prompts.set_inline,
            "active_ids": request.prompts.active_ids,
        },
        "outputs": {
            "save_annotated_video": request.run.save_annotated_video,
            "save_previews": request.run.save_previews,
        },
    }
    if request.run.stride is not None:
        raw["rate_control"] = {"stride": request.run.stride}
    return raw
```

- [ ] **Step 4: Verificar + suite completa**

Run: `pytest tests/test_run_request.py -q && pytest -q`
Expected: PASS todo.

- [ ] **Step 5: Commit**

```bash
git add src/eovrt_media/service/run_request.py tests/test_run_request.py
git commit -m "feat(service): RunRequest canonico y traduccion a run config"
```

---

### Task 6: Registro de plugins de ingesta

**Files:**
- Create: `src/eovrt_media/sources/registry.py`
- Modify: `src/eovrt_media/runtime/pipeline.py` (mover `create_source`, dejar re-export)
- Test: `tests/test_ingest_registry.py`

**Interfaces:**
- Consumes: `RunConfig`, sources existentes.
- Produces: `IngestPlugin` (dataclass: `id, kind: "bounded"|"live", available: bool, description: str`); `list_plugins() -> list[dict]`; `create_source(config: RunConfig) -> BaseSource` (misma semántica que el actual de `pipeline.py`, incluidos alias `video|video_frame|video_file`); `PluginUnavailableError(ValueError)` para `oak_d`. `runtime/pipeline.py` re-exporta `create_source` (compat tests existentes).

- [ ] **Step 1: Test que falla**

```python
# tests/test_ingest_registry.py
import pytest
from eovrt_media.sources.registry import (
    PluginUnavailableError,
    create_source,
    list_plugins,
)
from eovrt_media.config.loader import load_run_config_data
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SET_INLINE = {"id": "t", "classes": [{"id": "p", "phrasings": {"default": ["p"]}}]}


def _config(tmp_path, **source):
    raw = {
        "run": {},
        "source": source,
        "model": {"adapter": "mock"},
        "prompts": {"set_inline": SET_INLINE},
    }
    return load_run_config_data(raw, plane_root=REPO_ROOT / "configs")


def test_list_plugins_expone_los_cuatro():
    plugins = {p["id"]: p for p in list_plugins()}
    assert set(plugins) == {"image_folder", "video_file", "rtsp", "oak_d"}
    assert plugins["image_folder"]["kind"] == "bounded"
    assert plugins["rtsp"]["kind"] == "live"
    assert plugins["oak_d"]["available"] is False
    assert plugins["image_folder"]["available"] is True


def test_create_source_image_folder(tmp_path):
    config = _config(tmp_path, type="image_folder", path=str(tmp_path))
    source = create_source(config)
    assert type(source).__name__ == "ImageFolderSource"


def test_pipeline_reexporta_create_source():
    from eovrt_media.runtime.pipeline import create_source as pipeline_create_source
    from eovrt_media.sources.registry import create_source as registry_create_source
    assert pipeline_create_source is registry_create_source
```

(`oak_d` no se testea vía `load_run_config_data` porque `_validate_deployment` ya lo rechaza antes; el registro lo marca `available: False` para el catálogo.)

- [ ] **Step 2: Verificar que falla**

Run: `pytest tests/test_ingest_registry.py -q`
Expected: FAIL con `ModuleNotFoundError`

- [ ] **Step 3: Implementación**

```python
# src/eovrt_media/sources/registry.py
"""Registro explícito de plugins de ingesta visual (Spec A §5)."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING

from eovrt_media.sources import BaseSource, ImageFolderSource, VideoFileSource

if TYPE_CHECKING:
    from eovrt_media.config import RunConfig


class PluginUnavailableError(ValueError):
    """El plugin existe en el registro pero no está disponible en esta build."""


@dataclass(frozen=True)
class IngestPlugin:
    id: str
    kind: str  # bounded | live
    available: bool
    description: str


PLUGINS: dict[str, IngestPlugin] = {
    "image_folder": IngestPlugin("image_folder", "bounded", True, "Carpeta de imágenes (datasets)"),
    "video_file": IngestPlugin("video_file", "bounded", True, "Archivo de video local"),
    "rtsp": IngestPlugin("rtsp", "live", True, "Stream RTSP (cámara IP)"),
    "oak_d": IngestPlugin("oak_d", "live", False, "OAK-D Pro PoE (hardware no disponible)"),
}

_VIDEO_ALIASES = {"video", "video_frame", "video_file"}


def list_plugins() -> list[dict]:
    return [asdict(p) for p in PLUGINS.values()]


def create_source(config: "RunConfig") -> BaseSource:
    """Crea una fuente; RateGate aplica el stride después de la ingesta."""
    source_type = config.source.type.lower().strip()
    plugin_id = "video_file" if source_type in _VIDEO_ALIASES else source_type
    plugin = PLUGINS.get(plugin_id)
    if plugin is None:
        raise ValueError(
            f"Tipo de fuente '{source_type}' no soportado. "
            f"Plugins: {sorted(PLUGINS)}."
        )
    if not plugin.available:
        raise PluginUnavailableError(
            f"Plugin de ingesta '{plugin_id}' no disponible: {plugin.description}"
        )
    if plugin_id == "image_folder":
        return ImageFolderSource(
            folder_path=config.source.path,
            extensions=config.source.extensions,
            every_n=1,
            max_units=config.run.max_units,
        )
    if plugin_id == "video_file":
        return VideoFileSource(
            video_path=config.source.path,
            every_n=1,
            target_fps=None,
            max_units=config.run.max_units,
        )
    # rtsp (live)
    from eovrt_media.sources import RtspSource

    return RtspSource(
        url=config.source.url or config.source.path,
        reconnect_retries=config.source.reconnect_retries,
        reconnect_delay_ms=config.source.reconnect_delay_ms,
        max_units=config.run.max_units,
    )
```

En `runtime/pipeline.py`: borrar la función `create_source` local (líneas 36-72) y reemplazar por:

```python
from eovrt_media.sources.registry import create_source  # noqa: F401  (API pública estable)
```

(quitar los imports de `ImageFolderSource`/`VideoFileSource` que quedan sin uso).

- [ ] **Step 4: Verificar + suite completa**

Run: `pytest tests/test_ingest_registry.py -q && pytest -q && make lint`
Expected: PASS todo (los tests existentes que usan `pipeline.create_source` siguen andando por el re-export).

- [ ] **Step 5: Commit**

```bash
git add src/eovrt_media/sources/registry.py src/eovrt_media/runtime/pipeline.py tests/test_ingest_registry.py
git commit -m "feat(sources): registro de plugins de ingesta; create_source movido"
```

---

### Task 7: `MemoryTransportAdapter.close()` idempotente y no bloqueante

**Files:**
- Modify: `src/eovrt_media/transport/memory.py`
- Test: `tests/test_memory_transport_close.py`

**Interfaces:**
- Produces: `close()` idempotente que nunca bloquea; `offer()` tras close descarta la unidad (suma `units_dropped`) en vez de bloquear para siempre; `request()` devuelve `END` cuando la cola se agotó y el canal está cerrado, aunque el `END` sentinel no haya entrado en la cola.

- [ ] **Step 1: Test que falla**

```python
# tests/test_memory_transport_close.py
import threading
from eovrt_media.contracts.normalized_unit import END
from eovrt_media.transport.memory import MemoryTransportAdapter


class _Unit:  # stub mínimo, el transporte no inspecciona la unidad en deterministic
    pass


def test_close_idempotente_no_bloquea_con_cola_llena():
    t = MemoryTransportAdapter(policy="deterministic", max_queue_size=1)
    t.offer(_Unit())  # cola llena
    done = threading.Event()

    def _close_twice():
        t.close()
        t.close()
        done.set()

    threading.Thread(target=_close_twice, daemon=True).start()
    assert done.wait(timeout=2.0), "close() bloqueó con la cola llena"


def test_consumidor_recibe_end_tras_close_y_drain():
    t = MemoryTransportAdapter(policy="deterministic", max_queue_size=1)
    unit = _Unit()
    t.offer(unit)
    t.close()  # END no entra (cola llena)
    assert t.request() is unit
    assert t.request() is END


def test_offer_tras_close_descarta():
    t = MemoryTransportAdapter(policy="deterministic", max_queue_size=1)
    t.close()
    t.offer(_Unit())  # no debe bloquear
    assert t.units_dropped == 1
    assert t.request() is END
```

- [ ] **Step 2: Verificar que falla**

Run: `pytest tests/test_memory_transport_close.py -q`
Expected: FAIL (el primero cuelga → usar `timeout 60 pytest ...` si hace falta; el test ya usa wait con timeout, así que falla por assert).

- [ ] **Step 3: Implementación**

En `memory.py`, rama `deterministic` (la rama `bounded_freshness` ya es no bloqueante y tiene `_closed`):

```python
        if policy == "deterministic":
            self._q: queue.Queue = queue.Queue(maxsize=max_queue_size)
            self._det_closed = False
```

```python
    def offer(self, unit: NormalizedUnit) -> None:
        if self.policy == "deterministic":
            while not self._det_closed:
                try:
                    self._q.put(unit, timeout=0.1)  # backpressure con chequeo de cierre
                    return
                except queue.Full:
                    continue
            self.units_dropped += 1  # canal cerrado: descartar
        else:
            ...  # (rama bounded_freshness sin cambios)

    def close(self) -> None:
        if self.policy == "deterministic":
            if self._det_closed:
                return
            self._det_closed = True
            try:
                self._q.put_nowait(END)
            except queue.Full:
                pass  # request() detecta _det_closed al vaciar la cola
        else:
            ...  # (sin cambios)

    def request(self, current_time_ms=None) -> NormalizedUnit | type[END]:
        if self.policy == "deterministic":
            while True:
                try:
                    item = self._q.get(timeout=0.1)
                except queue.Empty:
                    if self._det_closed:
                        return END
                    continue
                return END if item is END else item
        else:
            ...  # (sin cambios)
```

- [ ] **Step 4: Verificar + suite completa**

Run: `pytest tests/test_memory_transport_close.py -q && pytest -q`
Expected: PASS todo (los tests de pipeline existentes validan la no-regresión del happy path).

- [ ] **Step 5: Commit**

```bash
git add src/eovrt_media/transport/memory.py tests/test_memory_transport_close.py
git commit -m "fix(transport): close() idempotente y no bloqueante en memoria"
```

---

### Task 8: Event sink + broadcaster con coalescing

**Files:**
- Create: `src/eovrt_media/service/events.py`
- Test: `tests/test_service_events.py`

**Interfaces:**
- Consumes: `RunArtifactWriter` (delegación), `DetectionEvent`/`MetricSample`/`ErrorEvent` (contracts).
- Produces: `RunEventSink` (Protocol con `emit(event: dict) -> None`); `EventEmittingArtifactWriter(inner, sink)` (delega TODO a inner y emite eventos `detection|metric|error`); `EventBroadcaster` (es un `RunEventSink`; `subscribe() -> Subscriber`, `unsubscribe(sub)`, `last_event_monotonic: float`); `Subscriber.push(event)` / `Subscriber.drain() -> list[dict]` (coalesce tipos `{"metric"}`: sólo el último; el resto en orden, deque acotada 200).

- [ ] **Step 1: Test que falla**

```python
# tests/test_service_events.py
from eovrt_media.service.events import EventBroadcaster, EventEmittingArtifactWriter


class _FakeWriter:
    def __init__(self):
        self.calls = []

    def write_metric(self, sample):
        self.calls.append(("metric", sample))

    def write_error(self, event):
        self.calls.append(("error", event))

    def close(self):
        self.calls.append(("close", None))


class _FakeMetric:
    unit_id = "u1"
    fps_effective = 2.0
    latency_total_ms = 500.0
    detections_count = 3
    gpu_memory_allocated_mb = 100.0


class _FakeError:
    unit_id = "u1"
    stage = "inference"
    message = "boom"


def test_writer_delega_y_emite():
    broadcaster = EventBroadcaster()
    sub = broadcaster.subscribe()
    inner = _FakeWriter()
    writer = EventEmittingArtifactWriter(inner, broadcaster)
    writer.write_metric(_FakeMetric())
    writer.write_error(_FakeError())
    writer.close()  # delegado vía __getattr__ o método explícito
    assert [c[0] for c in inner.calls] == ["metric", "error", "close"]
    events = sub.drain()
    types = [e["type"] for e in events]
    assert "metric" in types and "error" in types


def test_subscriber_coalesce_metricas():
    broadcaster = EventBroadcaster()
    sub = broadcaster.subscribe()
    for i in range(5):
        broadcaster.emit({"type": "metric", "unit_id": f"u{i}"})
    broadcaster.emit({"type": "error", "message": "x"})
    events = sub.drain()
    metrics = [e for e in events if e["type"] == "metric"]
    assert len(metrics) == 1 and metrics[0]["unit_id"] == "u4"  # solo la última
    assert len([e for e in events if e["type"] == "error"]) == 1
    assert sub.drain() == []  # drain vacía


def test_last_event_monotonic_avanza():
    broadcaster = EventBroadcaster()
    t0 = broadcaster.last_event_monotonic
    broadcaster.emit({"type": "metric"})
    assert broadcaster.last_event_monotonic >= t0
```

- [ ] **Step 2: Verificar que falla**

Run: `pytest tests/test_service_events.py -q`
Expected: FAIL con `ModuleNotFoundError`

- [ ] **Step 3: Implementación**

```python
# src/eovrt_media/service/events.py
"""Event sink in-process: pipeline → WebSocket, sin acoplar el pipeline al servidor."""
from __future__ import annotations

import time
from collections import deque
from threading import Lock
from typing import Any, Protocol

_COALESCE_TYPES = {"metric"}


class RunEventSink(Protocol):
    def emit(self, event: dict[str, Any]) -> None: ...


class Subscriber:
    """Cola por-suscriptor: coalesce métricas (último gana), acota lo discreto."""

    def __init__(self, max_discrete: int = 200) -> None:
        self._lock = Lock()
        self._latest: dict[str, dict[str, Any]] = {}
        self._discrete: deque[dict[str, Any]] = deque(maxlen=max_discrete)

    def push(self, event: dict[str, Any]) -> None:
        with self._lock:
            if event.get("type") in _COALESCE_TYPES:
                self._latest[event["type"]] = event
            else:
                self._discrete.append(event)

    def drain(self) -> list[dict[str, Any]]:
        with self._lock:
            out = list(self._discrete)
            self._discrete.clear()
            out.extend(self._latest.values())
            self._latest.clear()
            return out


class EventBroadcaster:
    """RunEventSink que reparte a N suscriptores; nunca bloquea al pipeline."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._subscribers: set[Subscriber] = set()
        self.last_event_monotonic: float = time.monotonic()

    def subscribe(self) -> Subscriber:
        sub = Subscriber()
        with self._lock:
            self._subscribers.add(sub)
        return sub

    def unsubscribe(self, sub: Subscriber) -> None:
        with self._lock:
            self._subscribers.discard(sub)

    def emit(self, event: dict[str, Any]) -> None:
        self.last_event_monotonic = time.monotonic()
        with self._lock:
            subscribers = list(self._subscribers)
        for sub in subscribers:
            sub.push(event)


class EventEmittingArtifactWriter:
    """Decora RunArtifactWriter: persiste como siempre y además emite eventos."""

    def __init__(self, inner: Any, sink: RunEventSink) -> None:
        self._inner = inner
        self._sink = sink

    def write_detection(self, event: Any) -> None:
        self._inner.write_detection(event)
        self._sink.emit(
            {"type": "detection", "unit_id": event.unit_id, "count": len(event.detections)}
        )

    def write_metric(self, sample: Any) -> None:
        self._inner.write_metric(sample)
        self._sink.emit(
            {
                "type": "metric",
                "unit_id": sample.unit_id,
                "fps": sample.fps_effective,
                "latency_total_ms": sample.latency_total_ms,
                "detections_count": sample.detections_count,
                "gpu_memory_mb": sample.gpu_memory_allocated_mb,
            }
        )

    def write_error(self, event: Any) -> None:
        self._inner.write_error(event)
        self._sink.emit(
            {
                "type": "error",
                "unit_id": getattr(event, "unit_id", None),
                "stage": getattr(event, "stage", None),
                "message": getattr(event, "message", None),
            }
        )

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)
```

- [ ] **Step 4: Verificar + suite completa**

Run: `pytest tests/test_service_events.py -q && pytest -q`
Expected: PASS todo.

- [ ] **Step 5: Commit**

```bash
git add src/eovrt_media/service/events.py tests/test_service_events.py
git commit -m "feat(service): event sink con broadcaster y coalescing"
```

---

### Task 9: Descomposición de `run_pipeline` → `execute_run` + `RunControl`

**Files:**
- Modify: `src/eovrt_media/runtime/pipeline.py`
- Test: `tests/test_execute_run.py`

**Interfaces:**
- Consumes: `create_source` (registry), `EventEmittingArtifactWriter`/`RunEventSink` (Task 8), `MemoryTransportAdapter.close()` arreglado (Task 7).
- Produces: `RunControl` (`request_stop()`, `stop_requested: bool`, `bind_source(source)`); `execute_run(config: RunConfig, adapter: BaseDetectorAdapter, *, console: Console | None = None, control: RunControl | None = None, event_sink: RunEventSink | None = None) -> str` — NO crea/carga/cierra el adapter. `run_pipeline(config, console=None)` conserva firma y semántica (crea adapter, load con status Rich, execute_run, close en finally).

- [ ] **Step 1: Test que falla**

```python
# tests/test_execute_run.py
import threading
import time
from pathlib import Path
from PIL import Image
from eovrt_media.config.loader import load_run_config_data
from eovrt_media.models import create_adapter
from eovrt_media.runtime.pipeline import RunControl, execute_run
from eovrt_media.service.events import EventBroadcaster

REPO_ROOT = Path(__file__).resolve().parents[1]
SET_INLINE = {"id": "t", "classes": [{"id": "p", "phrasings": {"default": ["p"]}}]}


def _make_images(folder: Path, n: int) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    for i in range(n):
        Image.new("RGB", (64, 48), (i * 10 % 255, 0, 0)).save(folder / f"img_{i:03d}.png")


def _config(tmp_path, images: Path, run_id: str, max_units=None):
    raw = {
        "run": {"id": run_id, "max_units": max_units},
        "source": {"type": "image_folder", "path": str(images)},
        "model": {"adapter": "mock"},
        "prompts": {"set_inline": SET_INLINE},
        "outputs": {"run_dir": str(tmp_path / "runs"), "save_previews": False},
    }
    return load_run_config_data(raw, plane_root=REPO_ROOT / "configs")


def test_dos_runs_secuenciales_con_el_mismo_adapter(tmp_path):
    images = tmp_path / "imgs"
    _make_images(images, 3)
    adapter = create_adapter(_config(tmp_path, images, "r1").model)
    adapter.load()
    try:
        rid1 = execute_run(_config(tmp_path, images, "r1"), adapter)
        rid2 = execute_run(_config(tmp_path, images, "r2"), adapter)  # adapter sigue vivo
    finally:
        adapter.close()
    for rid in (rid1, rid2):
        assert (tmp_path / "runs" / rid / "summary.json").exists()
        assert (tmp_path / "runs" / rid / "detections.jsonl").exists()


def test_stop_interrumpe_run_bounded(tmp_path):
    images = tmp_path / "imgs"
    _make_images(images, 300)
    config = _config(tmp_path, images, "r_stop")
    adapter = create_adapter(config.model)
    adapter.load()
    control = RunControl()
    result: dict = {}

    def _run():
        result["rid"] = execute_run(config, adapter, control=control)

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    time.sleep(0.3)
    control.request_stop()
    t.join(timeout=10.0)
    adapter.close()
    assert not t.is_alive(), "execute_run no terminó tras request_stop()"
    assert (tmp_path / "runs" / "r_stop" / "summary.json").exists()


def test_event_sink_recibe_metricas(tmp_path):
    images = tmp_path / "imgs"
    _make_images(images, 3)
    config = _config(tmp_path, images, "r_ev")
    adapter = create_adapter(config.model)
    adapter.load()
    broadcaster = EventBroadcaster()
    sub = broadcaster.subscribe()
    execute_run(config, adapter, event_sink=broadcaster)
    adapter.close()
    types = {e["type"] for e in sub.drain()}
    assert "metric" in types and "detection" in types
```

- [ ] **Step 2: Verificar que falla**

Run: `pytest tests/test_execute_run.py -q`
Expected: FAIL con `ImportError: cannot import name 'execute_run'`

- [ ] **Step 3: Implementación**

En `runtime/pipeline.py` (reemplaza el actual `run_pipeline`; `run_producer_loop`, `run_consumer_loop` y `_drain_producer_errors` no cambian):

```python
class RunControl:
    """Control de vida de un run: stop cooperativo desde otro thread."""

    def __init__(self) -> None:
        self._stop = threading.Event()
        self._source: BaseSource | None = None

    def bind_source(self, source: BaseSource) -> None:
        self._source = source

    def request_stop(self) -> None:
        self._stop.set()
        if self._source is not None:
            self._source.stop()  # destraba fuentes live bloqueadas en captura

    @property
    def stop_requested(self) -> bool:
        return self._stop.is_set()


def execute_run(
    config: RunConfig,
    adapter,
    *,
    console: Console | None = None,
    control: "RunControl | None" = None,
    event_sink=None,
) -> str:
    """Ejecuta un run con un adapter YA CARGADO (no lo crea, no lo cierra).

    Camino del servicio (Spec A §6): el modelo vive a nivel proceso; stop vía
    RunControl; telemetría opcional por event_sink (decorando el writer).
    """
    run_context = RunContext(config)
    artifact_writer = RunArtifactWriter(run_context)
    if event_sink is not None:
        from eovrt_media.service.events import EventEmittingArtifactWriter

        artifact_writer = EventEmittingArtifactWriter(artifact_writer, event_sink)
    tracker = LatencyTracker()
    producer = None

    if console is not None:
        console.print(f"[bold green]▶ Corrida:[/bold green] {run_context.run_id}")
        console.print(f"[dim]  Directorio de salida: {run_context.run_dir}[/dim]")

    try:
        if config.config_path:
            artifact_writer.write_original_config(config.config_path)
        artifact_writer.write_effective_config()

        source = create_source(config)
        if control is not None:
            control.bind_source(source)
        try:
            source_count = len(source)
            progress_total: int | None = source_count if source_count >= 0 else None
        except TypeError:
            progress_total = None
        normalizer = DetectionNormalizer(
            min_confidence=config.postprocess.min_confidence,
            min_box_area_px=config.postprocess.min_box_area_px,
            normalize_boxes=config.postprocess.normalize_boxes,
        )
        plan = config.build_prompt_plan(adapter.PROMPT_BACKEND)
        prompt_set_id = (
            config.prompts_file.resolved_set_id() if config.prompts_file else "unknown"
        )
        reset_gpu_peak_memory()

        rate_control = config.rate_control
        transport = create_transport(
            backend=config.transport.backend,
            policy=rate_control.policy,
            max_queue_size=rate_control.max_queue_size,
            buffer_size=rate_control.buffer_size,
            max_staleness_ms=rate_control.max_staleness_ms,
            endpoint=config.transport.endpoint,
        )
        should_continue = (
            (lambda: not control.stop_requested) if control is not None else None
        )
        timings: dict[str, float] = {"backpressure_wait_ms": 0.0}
        producer = threading.Thread(
            target=run_producer_loop,
            args=(
                source,
                RateGate(stride=rate_control.stride),
                adapter.input_spec,
                PayloadFormat(config.transport.payload_format),
                transport,
                run_context.run_id,
                run_context._errors_queue,
                timings,
                should_continue,
            ),
            daemon=True,
            name="pipeline-producer",
        )
        producer.start()

        def _consume(progress=None, task=None) -> None:
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
                drain_errors=True,
            )

        try:
            if console is not None:
                with Progress(
                    SpinnerColumn(),
                    TextColumn("[progress.description]{task.description}"),
                    BarColumn(),
                    TaskProgressColumn(),
                    console=console,
                ) as progress:
                    task = progress.add_task(
                        "Procesando unidades visuales...", total=progress_total
                    )
                    _consume(progress, task)
            else:
                _consume()
        except KeyboardInterrupt:
            if console is not None:
                console.print(
                    "\n[yellow]⚠ Corrida interrumpida — guardando artefactos...[/yellow]"
                )
            source.stop()
            transport.close()
            producer.join(timeout=5.0)

        _drain_producer_errors(run_context._errors_queue, artifact_writer, run_context)
        run_context.units_dropped = getattr(transport, "units_dropped", 0)
        run_context.backpressure_wait_ms = timings["backpressure_wait_ms"]
    finally:
        if producer is not None:
            producer.join(timeout=30.0)
        artifact_writer.close()

    run_context.gpu_memory_peak_mb = get_gpu_memory_peak_mb()
    run_context.finish()
    artifact_writer.write_summary(tracker)
    artifact_writer.write_provenance()
    artifact_writer.write_manifest()
    return run_context.run_id


def run_pipeline(config: RunConfig, console: Console | None = None) -> str:
    """Ejecuta una corrida creando y cargando el adapter (camino standalone/tests)."""
    console = console or Console()
    adapter = create_adapter(config.model)
    with console.status("[bold cyan]Cargando modelo..."):
        adapter.load()
    try:
        return execute_run(config, adapter, console=console)
    finally:
        adapter.close()
```

Detalle importante: el productor ahora sí recibe `should_continue` (posición 9 de la tupla `args`) — hoy `run_pipeline` no lo pasaba. Cuando `control` pide stop, el productor corta, `transport.close()` (finally del productor) inyecta `END` de forma no bloqueante (Task 7) y el consumidor termina.

- [ ] **Step 4: Verificar + suite completa**

Run: `pytest tests/test_execute_run.py -q && pytest -q`
Expected: PASS todo — en particular `tests/test_pipeline_mock.py` y `tests/test_pipeline_two_threads.py` intactos (validan la no-regresión de `run_pipeline`).

- [ ] **Step 5: Commit**

```bash
git add src/eovrt_media/runtime/pipeline.py tests/test_execute_run.py
git commit -m "refactor(runtime): execute_run con adapter inyectado, RunControl y event sink"
```

---

### Task 10: RunManager

**Files:**
- Create: `src/eovrt_media/service/run_manager.py`
- Test: `tests/test_run_manager.py`

**Interfaces:**
- Consumes: `execute_run`/`RunControl` (Task 9), `EventBroadcaster` (Task 8), `to_raw_run_config`/`RunRequest` (Task 5), `load_run_config_data` (Task 2), `find_plane_catalog_root`, `ServiceSettings` (Task 1), `ModelSection`.
- Produces: `RunManager(adapter, model_section: ModelSection, settings: ServiceSettings)` con: `start_run(request: RunRequest) -> str` (lanza `RunBusyError(active_run_id)` si ocupado; `ValueError` de validación propaga); `stop(run_id: str, cause: str = "stop")`; `stop_active(cause: str)`; `join_active(timeout: float)`; `get(run_id: str) -> dict` (lanza `UnknownRunError`); `list_runs() -> list[dict]`; `subscribe(run_id) -> Subscriber` / `unsubscribe(run_id, sub)`; `shutdown()` (corta watchdog). Estados: `running/succeeded/failed/stopped`; summary.json siempre escrito/parcheado con `status`, `stop_cause`, `error` (fuente de verdad del historial).

- [ ] **Step 1: Test que falla**

```python
# tests/test_run_manager.py
import json
import time
from pathlib import Path
import pytest
from PIL import Image
from eovrt_media.config.loader import resolve_model_ref
from eovrt_media.models import create_adapter
from eovrt_media.service.run_manager import RunBusyError, RunManager, UnknownRunError
from eovrt_media.service.run_request import RunRequest
from eovrt_media.service.settings import ServiceSettings

SET_INLINE = {"id": "t", "classes": [{"id": "p", "phrasings": {"default": ["p"]}}]}


@pytest.fixture()
def manager(tmp_path):
    model_section = resolve_model_ref("mock")
    adapter = create_adapter(model_section)
    adapter.load()
    settings = ServiceSettings.from_env(
        {"EOVRT_MODEL_REF": "mock", "EOVRT_RUNS_DIR": str(tmp_path / "runs"),
         "EOVRT_WATCHDOG_SECONDS": "60"}
    )
    m = RunManager(adapter, model_section, settings)
    yield m
    m.shutdown()
    adapter.close()


def _images(tmp_path, n=3):
    folder = tmp_path / "imgs"
    folder.mkdir(exist_ok=True)
    for i in range(n):
        Image.new("RGB", (64, 48), (10, 20, 30)).save(folder / f"i{i:03d}.png")
    return folder


def _request(folder, **run):
    return RunRequest(
        ingest={"plugin": "image_folder", "config": {"path": str(folder)}},
        prompts={"set_inline": SET_INLINE},
        run=run,
    )


def _wait_final(manager, run_id, timeout=15.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        status = manager.get(run_id)["status"]
        if status != "running":
            return status
        time.sleep(0.05)
    raise AssertionError("el run no terminó a tiempo")


def test_run_exitoso_y_summary_con_status(manager, tmp_path):
    run_id = manager.start_run(_request(_images(tmp_path)))
    assert _wait_final(manager, run_id) == "succeeded"
    summary = json.loads(
        (tmp_path / "runs" / run_id / "summary.json").read_text()
    )
    assert summary["status"] == "succeeded"


def test_busy_mientras_corre(manager, tmp_path):
    folder = _images(tmp_path, n=400)
    run_id = manager.start_run(_request(folder))
    with pytest.raises(RunBusyError):
        manager.start_run(_request(folder))
    manager.stop(run_id)
    assert _wait_final(manager, run_id) == "stopped"


def test_fallo_en_setup_escribe_summary_failed(manager, tmp_path):
    run_id = manager.start_run(_request(tmp_path / "no_existe"))
    status = _wait_final(manager, run_id)
    assert status == "failed"
    summary = json.loads((tmp_path / "runs" / run_id / "summary.json").read_text())
    assert summary["status"] == "failed" and summary["error"]


def test_get_desconocido(manager):
    with pytest.raises(UnknownRunError):
        manager.get("nope")


def test_list_runs_desde_disco(manager, tmp_path):
    run_id = manager.start_run(_request(_images(tmp_path)))
    _wait_final(manager, run_id)
    runs = manager.list_runs()
    assert any(r["run_id"] == run_id for r in runs)
```

(Si el fallo de setup con carpeta inexistente no lanza — `ImageFolderSource` podría producir 0 unidades — ajustar el test para provocar el fallo con `plugin: "video_file"` y un path inexistente, que sí falla al abrir.)

- [ ] **Step 2: Verificar que falla**

Run: `pytest tests/test_run_manager.py -q`
Expected: FAIL con `ModuleNotFoundError`

- [ ] **Step 3: Implementación**

```python
# src/eovrt_media/service/run_manager.py
"""RunManager: un run activo, stop/watchdog, summary como fuente de verdad."""
from __future__ import annotations

import json
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from eovrt_media.config.loader import find_plane_catalog_root, load_run_config_data
from eovrt_media.config.schemas import ModelSection
from eovrt_media.runtime.pipeline import RunControl, execute_run
from eovrt_media.service.events import EventBroadcaster, Subscriber
from eovrt_media.service.run_request import RunRequest, to_raw_run_config
from eovrt_media.service.settings import ServiceSettings


class RunBusyError(RuntimeError):
    def __init__(self, active_run_id: str) -> None:
        super().__init__(f"Ya hay un run activo: {active_run_id}")
        self.active_run_id = active_run_id


class UnknownRunError(KeyError):
    pass


@dataclass
class ActiveRun:
    run_id: str
    config: Any
    control: RunControl
    broadcaster: EventBroadcaster
    started_at: datetime
    thread: threading.Thread | None = None
    status: str = "running"
    stop_cause: str | None = None
    error: str | None = None
    finished: threading.Event = field(default_factory=threading.Event)


class RunManager:
    def __init__(
        self, adapter: Any, model_section: ModelSection, settings: ServiceSettings
    ) -> None:
        self._adapter = adapter
        self._model_section = model_section
        self._settings = settings
        self._lock = threading.Lock()
        self._active: ActiveRun | None = None
        self._closing = threading.Event()
        self._watchdog = threading.Thread(
            target=self._watchdog_loop, daemon=True, name="run-watchdog"
        )
        self._watchdog.start()

    # --- API ---

    def start_run(self, request: RunRequest) -> str:
        with self._lock:
            if self._active is not None:
                raise RunBusyError(self._active.run_id)
            raw = to_raw_run_config(request, self._model_section)
            raw.setdefault("outputs", {})["run_dir"] = str(self._settings.runs_dir)
            config = load_run_config_data(
                raw,
                plane_root=find_plane_catalog_root(None, self._settings.catalog_root),
                datasets_root=self._settings.datasets_root,
            )
            config.run.id = self._new_run_id(config)
            active = ActiveRun(
                run_id=config.run.id,
                config=config,
                control=RunControl(),
                broadcaster=EventBroadcaster(),
                started_at=datetime.now(timezone.utc),
            )
            self._active = active
        thread = threading.Thread(
            target=self._execute, args=(active,), daemon=True, name="run-executor"
        )
        active.thread = thread
        thread.start()
        return active.run_id

    def stop(self, run_id: str, cause: str = "stop") -> None:
        with self._lock:
            active = self._active
            if active is None or active.run_id != run_id:
                raise UnknownRunError(run_id)
            if active.stop_cause is None:
                active.stop_cause = cause
        active.control.request_stop()

    def stop_active(self, cause: str) -> None:
        with self._lock:
            active = self._active
        if active is not None:
            self.stop(active.run_id, cause=cause)

    def join_active(self, timeout: float) -> None:
        with self._lock:
            active = self._active
        if active is not None:
            active.finished.wait(timeout=timeout)

    def get(self, run_id: str) -> dict[str, Any]:
        with self._lock:
            active = self._active
        if active is not None and active.run_id == run_id:
            return {
                "run_id": run_id,
                "status": active.status,
                "started_at": active.started_at.isoformat(),
                "model": self._model_section.ref,
            }
        summary_path = self._settings.runs_dir / run_id / "summary.json"
        if not summary_path.exists():
            raise UnknownRunError(run_id)
        summary = json.loads(summary_path.read_text())
        return {
            "run_id": run_id,
            "status": summary.get("status", "unknown"),
            "summary": summary,
        }

    def list_runs(self) -> list[dict[str, Any]]:
        runs: list[dict[str, Any]] = []
        with self._lock:
            active = self._active
        if active is not None:
            runs.append({"run_id": active.run_id, "status": active.status})
        runs_dir = self._settings.runs_dir
        if runs_dir.is_dir():
            dirs = sorted(
                (d for d in runs_dir.iterdir() if d.is_dir()),
                key=lambda d: d.stat().st_mtime,
                reverse=True,
            )
            for d in dirs:
                if active is not None and d.name == active.run_id:
                    continue
                summary_path = d / "summary.json"
                if summary_path.exists():
                    summary = json.loads(summary_path.read_text())
                    runs.append(
                        {"run_id": d.name, "status": summary.get("status", "unknown")}
                    )
        return runs

    def subscribe(self, run_id: str) -> Subscriber:
        with self._lock:
            active = self._active
        if active is None or active.run_id != run_id:
            raise UnknownRunError(run_id)
        return active.broadcaster.subscribe()

    def unsubscribe(self, run_id: str, sub: Subscriber) -> None:
        with self._lock:
            active = self._active
        if active is not None and active.run_id == run_id:
            active.broadcaster.unsubscribe(sub)

    def shutdown(self) -> None:
        self._closing.set()

    # --- interno ---

    def _new_run_id(self, config: Any) -> str:
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        model = (self._model_section.name or self._model_section.adapter or "model").lower()
        # sufijo único: el default de RunContext (segundos) colisiona (Spec A §3.1)
        return f"run_{ts}_{config.run.scenario.lower()}_{model}_{uuid.uuid4().hex[:6]}"

    def _execute(self, active: ActiveRun) -> None:
        status, error = "succeeded", None
        try:
            execute_run(
                active.config,
                self._adapter,
                control=active.control,
                event_sink=active.broadcaster,
            )
        except Exception as exc:  # noqa: BLE001 — el estado failed captura la causa
            status, error = "failed", str(exc)
        if active.control.stop_requested and status == "succeeded":
            status = "failed" if active.stop_cause == "stalled" else "stopped"
        self._finalize(active, status, error)

    def _finalize(self, active: ActiveRun, status: str, error: str | None) -> None:
        run_dir = self._settings.runs_dir / active.run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        summary_path = run_dir / "summary.json"
        summary: dict[str, Any] = (
            json.loads(summary_path.read_text()) if summary_path.exists() else {}
        )
        summary.setdefault("run_id", active.run_id)
        summary["status"] = status
        summary["stop_cause"] = active.stop_cause
        summary["error"] = error
        summary_path.write_text(json.dumps(summary, indent=2))
        active.status = status
        active.error = error
        active.broadcaster.emit({"type": "state", "status": status, "error": error})
        active.finished.set()
        with self._lock:
            self._active = None

    def _watchdog_loop(self) -> None:
        while not self._closing.wait(timeout=5.0):
            with self._lock:
                active = self._active
            if active is None or active.stop_cause is not None:
                continue
            idle = time.monotonic() - active.broadcaster.last_event_monotonic
            if idle > self._settings.watchdog_seconds:
                active.stop_cause = "stalled"
                active.control.request_stop()
```

- [ ] **Step 4: Verificar + suite completa**

Run: `pytest tests/test_run_manager.py -q && pytest -q`
Expected: PASS todo.

- [ ] **Step 5: Commit**

```bash
git add src/eovrt_media/service/run_manager.py tests/test_run_manager.py
git commit -m "feat(service): RunManager con un run activo, stop, watchdog y finalize"
```

---

### Task 11: Startup (carga de modelo), `/api/model`, retención y shutdown

**Files:**
- Create: `src/eovrt_media/service/retention.py`, `src/eovrt_media/service/routers/model.py`
- Modify: `src/eovrt_media/service/app.py` (lifespan real), `tests/test_service_health.py` (actualizar el test de readyz)
- Test: `tests/test_service_startup.py`, `tests/test_retention.py`

**Interfaces:**
- Consumes: `resolve_model_ref` (Task 2), `create_adapter`, `RunManager` (Task 10), `ServiceSettings`.
- Produces: lifespan que puebla `app.state.model_section`, `app.state.adapter`, `app.state.manager`, `app.state.ready`; en shutdown: `manager.stop_active("shutdown")` + `join_active(grace)` + `manager.shutdown()` + `adapter.close()`. `GET /api/model` → `{ref, name, adapter, device, thresholds{box, text, confidence, iou}, runtime{half_precision, warmup}}`. `gc_runs_dir(settings) -> list[str]` (ids eliminados por edad/tamaño).

- [ ] **Step 1: Tests que fallan**

```python
# tests/test_service_startup.py
import json
from fastapi.testclient import TestClient
from eovrt_media.service.app import create_app
from eovrt_media.service.settings import ServiceSettings


def _settings(tmp_path, model_ref="mock"):
    return ServiceSettings.from_env(
        {"EOVRT_MODEL_REF": model_ref, "EOVRT_RUNS_DIR": str(tmp_path / "runs")}
    )


def test_startup_carga_modelo_y_ready(tmp_path):
    with TestClient(create_app(_settings(tmp_path))) as client:
        r = client.get("/readyz")
        assert r.status_code == 200
        assert r.json()["model"] == "mock"
        m = client.get("/api/model").json()
        assert (m["adapter"] or m["name"]) == "mock"
        assert "thresholds" in m and "device" in m


def test_startup_modelo_invalido_no_ready(tmp_path):
    with TestClient(create_app(_settings(tmp_path, model_ref="no/existe"))) as client:
        r = client.get("/readyz")
        assert r.status_code == 503
        assert r.json()["error"]
        assert client.get("/healthz").status_code == 200  # proceso vivo igual
```

```python
# tests/test_retention.py
import time
from pathlib import Path
from eovrt_media.service.retention import gc_runs_dir
from eovrt_media.service.settings import ServiceSettings


def _mkrun(runs: Path, name: str, age_days: float = 0.0, size_bytes: int = 10):
    d = runs / name
    d.mkdir(parents=True)
    (d / "summary.json").write_bytes(b"x" * size_bytes)
    old = time.time() - age_days * 86400
    import os
    os.utime(d, (old, old))
    return d


def test_gc_por_edad(tmp_path):
    runs = tmp_path / "runs"
    _mkrun(runs, "viejo", age_days=10)
    _mkrun(runs, "nuevo", age_days=0)
    settings = ServiceSettings.from_env({
        "EOVRT_MODEL_REF": "mock", "EOVRT_RUNS_DIR": str(runs),
        "EOVRT_RUNS_MAX_AGE_DAYS": "7",
    })
    removed = gc_runs_dir(settings)
    assert removed == ["viejo"]
    assert not (runs / "viejo").exists() and (runs / "nuevo").exists()


def test_gc_sin_limites_no_borra(tmp_path):
    runs = tmp_path / "runs"
    _mkrun(runs, "a")
    settings = ServiceSettings.from_env(
        {"EOVRT_MODEL_REF": "mock", "EOVRT_RUNS_DIR": str(runs)}
    )
    assert gc_runs_dir(settings) == []
```

Además, en `tests/test_service_health.py` **reemplazar** `test_readyz_503_sin_modelo` (ya no aplica: el lifespan ahora carga `mock`) por:

```python
def test_readyz_503_con_modelo_invalido():
    from eovrt_media.service.settings import ServiceSettings
    settings = ServiceSettings.from_env({"EOVRT_MODEL_REF": "no/existe"})
    with TestClient(create_app(settings)) as client:
        assert client.get("/readyz").status_code == 503
```

- [ ] **Step 2: Verificar que fallan**

Run: `pytest tests/test_service_startup.py tests/test_retention.py -q`
Expected: FAIL (`/api/model` 404, readyz 503 con mock, `ModuleNotFoundError: retention`)

- [ ] **Step 3: Implementación**

```python
# src/eovrt_media/service/retention.py
"""Retención de RUNS_DIR: GC por antigüedad y tamaño total (Spec A §7.4)."""
from __future__ import annotations

import shutil
import time
from pathlib import Path

from eovrt_media.service.settings import ServiceSettings


def _dir_size_bytes(path: Path) -> int:
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file())


def gc_runs_dir(settings: ServiceSettings) -> list[str]:
    runs_dir = settings.runs_dir
    if not runs_dir.is_dir():
        return []
    removed: list[str] = []
    dirs = sorted(
        (d for d in runs_dir.iterdir() if d.is_dir()), key=lambda d: d.stat().st_mtime
    )
    if settings.retention_max_age_days is not None:
        cutoff = time.time() - settings.retention_max_age_days * 86400
        for d in list(dirs):
            if d.stat().st_mtime < cutoff:
                shutil.rmtree(d, ignore_errors=True)
                removed.append(d.name)
                dirs.remove(d)
    if settings.retention_max_total_gb is not None:
        limit = settings.retention_max_total_gb * 1024**3
        sizes = {d: _dir_size_bytes(d) for d in dirs}
        total = sum(sizes.values())
        for d in list(dirs):  # más viejo primero
            if total <= limit:
                break
            shutil.rmtree(d, ignore_errors=True)
            removed.append(d.name)
            total -= sizes[d]
    return removed
```

```python
# src/eovrt_media/service/routers/model.py
"""GET /api/model — el modelo fijo de esta instancia (Spec A §3.1)."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

router = APIRouter(prefix="/api")


@router.get("/model")
def get_model(request: Request) -> dict:
    section = getattr(request.app.state, "model_section", None)
    if section is None:
        raise HTTPException(status_code=503, detail="Modelo no cargado")
    return {
        "ref": section.ref,
        "name": section.name,
        "adapter": section.adapter,
        "device": section.device,
        "thresholds": {
            "box": section.box_threshold,
            "text": section.text_threshold,
            "confidence": section.confidence_threshold,
            "iou": section.iou_threshold,
        },
        "runtime": {
            "half_precision": section.runtime.half_precision,
            "warmup": section.runtime.warmup,
        },
    }
```

`app.py` — lifespan real (reemplaza el stub):

```python
# src/eovrt_media/service/app.py
"""Factory de la app FastAPI del servicio media-plane."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from starlette.concurrency import run_in_threadpool

from eovrt_media.service.retention import gc_runs_dir
from eovrt_media.service.routers import health, model
from eovrt_media.service.settings import ServiceSettings

logger = logging.getLogger(__name__)


@asynccontextmanager
async def _lifespan(app: FastAPI):
    settings: ServiceSettings = app.state.settings
    adapter = None
    try:
        from eovrt_media.config.loader import resolve_model_ref
        from eovrt_media.models import create_adapter
        from eovrt_media.service.run_manager import RunManager

        model_section = resolve_model_ref(settings.model_ref, settings.catalog_root)
        if settings.model_device:
            model_section.device = settings.model_device
        adapter = create_adapter(model_section)
        await run_in_threadpool(adapter.load)  # carga (y warmup) UNA vez
        app.state.model_section = model_section
        app.state.adapter = adapter
        app.state.manager = RunManager(adapter, model_section, settings)
        app.state.ready = True
        logger.info("Modelo %s cargado (device=%s)", settings.model_ref, model_section.device)
    except Exception as exc:  # noqa: BLE001 — /readyz reporta la causa; sin recarga (Spec A §8)
        app.state.load_error = str(exc)
        logger.exception("Fallo de carga del modelo %s", settings.model_ref)
    removed = gc_runs_dir(settings)
    if removed:
        logger.info("GC de retención: %d runs eliminados", len(removed))
    yield
    # SIGTERM/shutdown = camino stop (Spec A §4): el redeploy es el caso normal
    manager = getattr(app.state, "manager", None)
    if manager is not None:
        manager.stop_active(cause="shutdown")
        manager.join_active(timeout=settings.shutdown_grace_seconds)
        manager.shutdown()
    if adapter is not None:
        adapter.close()


def create_app(settings: ServiceSettings | None = None) -> FastAPI:
    settings = settings or ServiceSettings.from_env()
    app = FastAPI(title="eovrt-media-plane", lifespan=_lifespan)
    app.state.settings = settings
    app.state.ready = False
    app.state.load_error = None
    app.include_router(health.router)
    app.include_router(model.router)
    return app
```

- [ ] **Step 4: Verificar + suite completa**

Run: `pytest tests/test_service_startup.py tests/test_retention.py tests/test_service_health.py -q && pytest -q`
Expected: PASS todo.

- [ ] **Step 5: Commit**

```bash
git add src/eovrt_media/service tests/test_service_startup.py tests/test_retention.py tests/test_service_health.py
git commit -m "feat(service): carga de modelo al startup, /api/model, retencion y shutdown limpio"
```

---

### Task 12: Router de runs (POST/GET/stop/DELETE + historial)

**Files:**
- Create: `src/eovrt_media/service/routers/runs.py`
- Modify: `src/eovrt_media/service/app.py` (incluir router)
- Test: `tests/test_runs_api.py`

**Interfaces:**
- Consumes: `RunManager` (`app.state.manager`), `RunRequest` (Task 5), `RunBusyError`/`UnknownRunError`.
- Produces: `POST /api/runs` (body `RunRequest` → 201 `{run_id}`; 503 si not ready; 409 `{detail, active_run_id}`; 422 por validación FastAPI o `ValueError` del loader); `GET /api/runs/{id}`; `GET /api/runs`; `POST /api/runs/{id}/stop` → 202; `DELETE /api/runs/{id}` → 204 (409 si activo, 404 si no existe).

- [ ] **Step 1: Test que falla**

```python
# tests/test_runs_api.py
import time
import pytest
from PIL import Image
from fastapi.testclient import TestClient
from eovrt_media.service.app import create_app
from eovrt_media.service.settings import ServiceSettings

SET_INLINE = {"id": "t", "classes": [{"id": "p", "phrasings": {"default": ["p"]}}]}


@pytest.fixture()
def client(tmp_path):
    settings = ServiceSettings.from_env(
        {"EOVRT_MODEL_REF": "mock", "EOVRT_RUNS_DIR": str(tmp_path / "runs")}
    )
    with TestClient(create_app(settings)) as c:
        yield c


def _images(tmp_path, n=3):
    folder = tmp_path / "imgs"
    folder.mkdir(exist_ok=True)
    for i in range(n):
        Image.new("RGB", (64, 48), (1, 2, 3)).save(folder / f"i{i:03d}.png")
    return folder


def _body(folder, **run):
    return {
        "ingest": {"plugin": "image_folder", "config": {"path": str(folder)}},
        "prompts": {"set_inline": SET_INLINE},
        "run": run,
    }


def _wait_final(client, run_id, timeout=15.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        status = client.get(f"/api/runs/{run_id}").json()["status"]
        if status != "running":
            return status
        time.sleep(0.05)
    raise AssertionError("run no terminó")


def test_ciclo_completo(client, tmp_path):
    r = client.post("/api/runs", json=_body(_images(tmp_path)))
    assert r.status_code == 201
    run_id = r.json()["run_id"]
    assert _wait_final(client, run_id) == "succeeded"
    listado = client.get("/api/runs").json()
    assert any(item["run_id"] == run_id for item in listado)


def test_seccion_model_es_422(client, tmp_path):
    body = _body(_images(tmp_path))
    body["model"] = {"ref": "yoloe/yoloe-26s"}
    assert client.post("/api/runs", json=body).status_code == 422


def test_busy_409_y_stop(client, tmp_path):
    folder = _images(tmp_path, n=400)
    run_id = client.post("/api/runs", json=_body(folder)).json()["run_id"]
    r = client.post("/api/runs", json=_body(folder))
    assert r.status_code == 409
    assert r.json()["active_run_id"] == run_id
    assert client.post(f"/api/runs/{run_id}/stop").status_code == 202
    assert _wait_final(client, run_id) == "stopped"


def test_delete_run_terminado(client, tmp_path):
    run_id = client.post("/api/runs", json=_body(_images(tmp_path))).json()["run_id"]
    _wait_final(client, run_id)
    assert client.delete(f"/api/runs/{run_id}").status_code == 204
    assert client.get(f"/api/runs/{run_id}").status_code == 404


def test_404_desconocido(client):
    assert client.get("/api/runs/nope").status_code == 404
```

- [ ] **Step 2: Verificar que falla**

Run: `pytest tests/test_runs_api.py -q`
Expected: FAIL con 404 en `POST /api/runs`

- [ ] **Step 3: Implementación**

```python
# src/eovrt_media/service/routers/runs.py
"""API de control de runs (Spec A §3.1)."""
from __future__ import annotations

import shutil

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, Response

from eovrt_media.service.run_manager import RunBusyError, RunManager, UnknownRunError
from eovrt_media.service.run_request import RunRequest

router = APIRouter(prefix="/api")


def _manager(request: Request) -> RunManager:
    if not getattr(request.app.state, "ready", False):
        raise HTTPException(status_code=503, detail="Servicio no listo (modelo no cargado)")
    return request.app.state.manager


@router.post("/runs", status_code=201)
def create_run(body: RunRequest, request: Request):
    manager = _manager(request)
    try:
        run_id = manager.start_run(body)
    except RunBusyError as exc:
        return JSONResponse(
            status_code=409,
            content={"detail": str(exc), "active_run_id": exc.active_run_id},
        )
    except (ValueError, FileNotFoundError) as exc:
        # errores del loader/registro (config inválida, ref inexistente, plugin no disponible)
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"run_id": run_id}


@router.get("/runs")
def list_runs(request: Request):
    return _manager(request).list_runs()


@router.get("/runs/{run_id}")
def get_run(run_id: str, request: Request):
    try:
        return _manager(request).get(run_id)
    except UnknownRunError as exc:
        raise HTTPException(status_code=404, detail=f"Run desconocido: {run_id}") from exc


@router.post("/runs/{run_id}/stop", status_code=202)
def stop_run(run_id: str, request: Request):
    try:
        _manager(request).stop(run_id)
    except UnknownRunError as exc:
        raise HTTPException(status_code=404, detail=f"Run desconocido: {run_id}") from exc
    return {"run_id": run_id, "stopping": True}


@router.delete("/runs/{run_id}", status_code=204)
def delete_run(run_id: str, request: Request):
    manager = _manager(request)
    try:
        info = manager.get(run_id)
    except UnknownRunError as exc:
        raise HTTPException(status_code=404, detail=f"Run desconocido: {run_id}") from exc
    if info["status"] == "running":
        raise HTTPException(status_code=409, detail="No se puede borrar un run activo")
    run_dir = request.app.state.settings.runs_dir / run_id
    shutil.rmtree(run_dir, ignore_errors=True)
    return Response(status_code=204)
```

En `app.py`, agregar `from eovrt_media.service.routers import runs` y `app.include_router(runs.router)`.

- [ ] **Step 4: Verificar + suite completa**

Run: `pytest tests/test_runs_api.py -q && pytest -q`
Expected: PASS todo.

- [ ] **Step 5: Commit**

```bash
git add src/eovrt_media/service/routers/runs.py src/eovrt_media/service/app.py tests/test_runs_api.py
git commit -m "feat(service): API de runs (create/status/list/stop/delete)"
```

---

### Task 13: WebSocket `/api/runs/{id}/stream`

**Files:**
- Create: `src/eovrt_media/service/routers/stream.py`
- Modify: `src/eovrt_media/service/app.py` (incluir router)
- Test: `tests/test_stream_ws.py`

**Interfaces:**
- Consumes: `RunManager.subscribe/unsubscribe/get`, `Subscriber.drain()`.
- Produces: `WS /api/runs/{run_id}/stream` — envía JSON por evento; cuando el run termina envía `{"type":"state","status":...}` y cierra. Run inexistente → close code 4404. Run ya terminado → envía el estado final y cierra.

- [ ] **Step 1: Test que falla**

```python
# tests/test_stream_ws.py
import time
import pytest
from PIL import Image
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect
from eovrt_media.service.app import create_app
from eovrt_media.service.settings import ServiceSettings

SET_INLINE = {"id": "t", "classes": [{"id": "p", "phrasings": {"default": ["p"]}}]}


@pytest.fixture()
def client(tmp_path):
    settings = ServiceSettings.from_env(
        {"EOVRT_MODEL_REF": "mock", "EOVRT_RUNS_DIR": str(tmp_path / "runs")}
    )
    with TestClient(create_app(settings)) as c:
        yield c


def _launch(client, tmp_path, n=100):
    folder = tmp_path / "imgs"
    folder.mkdir(exist_ok=True)
    for i in range(n):
        Image.new("RGB", (64, 48), (1, 2, 3)).save(folder / f"i{i:03d}.png")
    body = {
        "ingest": {"plugin": "image_folder", "config": {"path": str(folder)}},
        "prompts": {"set_inline": SET_INLINE},
        "run": {},
    }
    return client.post("/api/runs", json=body).json()["run_id"]


def test_stream_emite_y_termina_con_estado(client, tmp_path):
    run_id = _launch(client, tmp_path)
    received = []
    with client.websocket_connect(f"/api/runs/{run_id}/stream") as ws:
        while True:
            try:
                received.append(ws.receive_json())
            except WebSocketDisconnect:
                break
            if received and received[-1].get("type") == "state":
                break
    assert received[-1]["type"] == "state"
    assert received[-1]["status"] in {"succeeded", "stopped", "failed"}


def test_stream_run_desconocido_cierra_4404(client):
    with pytest.raises(WebSocketDisconnect) as excinfo:
        with client.websocket_connect("/api/runs/nope/stream") as ws:
            ws.receive_json()
    assert excinfo.value.code == 4404


def test_stream_run_terminado_envia_estado_final(client, tmp_path):
    run_id = _launch(client, tmp_path, n=3)
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if client.get(f"/api/runs/{run_id}").json()["status"] != "running":
            break
        time.sleep(0.05)
    with client.websocket_connect(f"/api/runs/{run_id}/stream") as ws:
        msg = ws.receive_json()
    assert msg["type"] == "state" and msg["status"] != "running"
```

- [ ] **Step 2: Verificar que falla**

Run: `pytest tests/test_stream_ws.py -q`
Expected: FAIL (403/404 del WS inexistente)

- [ ] **Step 3: Implementación**

```python
# src/eovrt_media/service/routers/stream.py
"""Streaming de telemetría por WebSocket con coalescing (Spec A §3.1)."""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, WebSocket

from eovrt_media.service.run_manager import UnknownRunError

router = APIRouter(prefix="/api")

_POLL_SECONDS = 0.2


@router.websocket("/runs/{run_id}/stream")
async def stream_run(ws: WebSocket, run_id: str) -> None:
    manager = getattr(ws.app.state, "manager", None)
    if manager is None:
        await ws.accept()
        await ws.close(code=4503)
        return
    try:
        info = manager.get(run_id)
    except UnknownRunError:
        await ws.accept()
        await ws.close(code=4404)
        return

    await ws.accept()
    if info["status"] != "running":
        await ws.send_json({"type": "state", "status": info["status"]})
        await ws.close()
        return

    try:
        sub = manager.subscribe(run_id)
    except UnknownRunError:
        # terminó entre el get y el subscribe
        await ws.send_json({"type": "state", "status": manager.get(run_id)["status"]})
        await ws.close()
        return

    try:
        while True:
            for event in sub.drain():
                await ws.send_json(event)
            status = manager.get(run_id)["status"]
            if status != "running":
                await ws.send_json({"type": "state", "status": status})
                break
            await asyncio.sleep(_POLL_SECONDS)
    finally:
        manager.unsubscribe(run_id, sub)
        await ws.close()
```

En `app.py`, incluir `stream.router`.

Nota: el `{"type":"state",...}` final también lo emite el broadcaster en `_finalize`; puede llegar duplicado por el drain — aceptable (el cliente coalesce por tipo). Si un test lo detecta, dedupe en el loop comparando con el último enviado.

- [ ] **Step 4: Verificar + suite completa**

Run: `pytest tests/test_stream_ws.py -q && pytest -q`
Expected: PASS todo.

- [ ] **Step 5: Commit**

```bash
git add src/eovrt_media/service/routers/stream.py src/eovrt_media/service/app.py tests/test_stream_ws.py
git commit -m "feat(service): WebSocket de telemetria con coalescing"
```

---

### Task 14: Artefactos (detections paginadas + archivos con Range)

**Files:**
- Modify: `src/eovrt_media/service/routers/runs.py`
- Test: `tests/test_artifacts_api.py`

**Interfaces:**
- Produces: `GET /api/runs/{id}/detections?page=1&page_size=100` → `{page, page_size, total, items}` (líneas de `detections.jsonl` parseadas); `GET /api/runs/{id}/artifacts/{path:path}` → `FileResponse` (Starlette ≥0.36 sirve Range → 206 para video); traversal fuera del run_dir → 404.

- [ ] **Step 1: Test que falla**

```python
# tests/test_artifacts_api.py
import json
import pytest
from fastapi.testclient import TestClient
from eovrt_media.service.app import create_app
from eovrt_media.service.settings import ServiceSettings


@pytest.fixture()
def client_y_run(tmp_path):
    runs = tmp_path / "runs"
    run_dir = runs / "run_x"
    run_dir.mkdir(parents=True)
    detections = [{"unit_id": f"u{i}", "detections": []} for i in range(25)]
    (run_dir / "detections.jsonl").write_text(
        "\n".join(json.dumps(d) for d in detections) + "\n"
    )
    (run_dir / "summary.json").write_text(json.dumps({"run_id": "run_x", "status": "succeeded"}))
    (run_dir / "annotated.mp4").write_bytes(b"0123456789abcdef")
    settings = ServiceSettings.from_env(
        {"EOVRT_MODEL_REF": "mock", "EOVRT_RUNS_DIR": str(runs)}
    )
    with TestClient(create_app(settings)) as c:
        yield c


def test_detections_paginadas(client_y_run):
    r = client_y_run.get("/api/runs/run_x/detections?page=2&page_size=10")
    assert r.status_code == 200
    data = r.json()
    assert data["total"] == 25
    assert len(data["items"]) == 10
    assert data["items"][0]["unit_id"] == "u10"


def test_artifact_con_range(client_y_run):
    r = client_y_run.get(
        "/api/runs/run_x/artifacts/annotated.mp4", headers={"Range": "bytes=0-3"}
    )
    assert r.status_code == 206
    assert r.content == b"0123"


def test_artifact_traversal_404(client_y_run):
    r = client_y_run.get("/api/runs/run_x/artifacts/..%2F..%2Fetc%2Fpasswd")
    assert r.status_code == 404


def test_artifact_inexistente_404(client_y_run):
    assert client_y_run.get("/api/runs/run_x/artifacts/nada.bin").status_code == 404
```

- [ ] **Step 2: Verificar que falla**

Run: `pytest tests/test_artifacts_api.py -q`
Expected: FAIL con 404 en `/detections`

- [ ] **Step 3: Implementación**

Agregar a `routers/runs.py`:

```python
import json as _json

from fastapi import Query
from fastapi.responses import FileResponse


@router.get("/runs/{run_id}/detections")
def get_detections(
    run_id: str,
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(100, ge=1, le=1000),
):
    _manager(request)  # 503 si no ready
    path = request.app.state.settings.runs_dir / run_id / "detections.jsonl"
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"Sin detecciones para: {run_id}")
    lines = path.read_text().splitlines()
    start = (page - 1) * page_size
    items = [_json.loads(line) for line in lines[start : start + page_size] if line]
    return {"page": page, "page_size": page_size, "total": len(lines), "items": items}


@router.get("/runs/{run_id}/artifacts/{artifact_path:path}")
def get_artifact(run_id: str, artifact_path: str, request: Request):
    run_dir = (request.app.state.settings.runs_dir / run_id).resolve()
    target = (run_dir / artifact_path).resolve()
    if not target.is_relative_to(run_dir) or not target.is_file():
        raise HTTPException(status_code=404, detail="Artefacto no encontrado")
    return FileResponse(target)  # Starlette >=0.36 maneja Range (206) para video
```

- [ ] **Step 4: Verificar + suite completa**

Run: `pytest tests/test_artifacts_api.py -q && pytest -q`
Expected: PASS todo. Si el Range devolviera 200 (Starlette vieja), subir el pin de fastapi en `pyproject.toml` y reinstalar.

- [ ] **Step 5: Commit**

```bash
git add src/eovrt_media/service/routers/runs.py tests/test_artifacts_api.py
git commit -m "feat(service): detections paginadas y artefactos con range requests"
```

---

### Task 15: Catálogos (`ingest-plugins`, `datasets`)

**Files:**
- Create: `src/eovrt_media/service/routers/catalog.py`
- Modify: `src/eovrt_media/service/app.py` (incluir router)
- Test: `tests/test_catalog_api.py`

**Interfaces:**
- Consumes: `list_plugins()` (Task 6), `find_plane_catalog_root`, `rebase_dataset_path` (Task 4).
- Produces: `GET /api/catalog/ingest-plugins` → lista del registro; `GET /api/catalog/datasets` → `[{id, description, path, available}]` desde `configs/datasets/*.yaml` (available = el path rebasado existe en disco).

- [ ] **Step 1: Test que falla**

```python
# tests/test_catalog_api.py
import pytest
import yaml
from fastapi.testclient import TestClient
from eovrt_media.service.app import create_app
from eovrt_media.service.settings import ServiceSettings


@pytest.fixture()
def client(tmp_path):
    # catálogo propio del test para no depender de los datasets reales
    catalog = tmp_path / "configs"
    (catalog / "datasets").mkdir(parents=True)
    (catalog / "models").mkdir()
    (catalog / "models" / "mock.yaml").write_text(yaml.safe_dump({"adapter": "mock"}))
    existing = tmp_path / "data"
    existing.mkdir()
    (catalog / "datasets" / "demo.yaml").write_text(
        yaml.safe_dump({"type": "image_folder", "path": str(existing), "description": "demo"})
    )
    (catalog / "datasets" / "roto.yaml").write_text(
        yaml.safe_dump({"type": "image_folder", "path": "/no/existe"})
    )
    settings = ServiceSettings.from_env({
        "EOVRT_MODEL_REF": "mock",
        "EOVRT_RUNS_DIR": str(tmp_path / "runs"),
        "EOVRT_MEDIA_CATALOG_ROOT": str(catalog),
    })
    with TestClient(create_app(settings)) as c:
        yield c


def test_ingest_plugins(client):
    plugins = {p["id"]: p for p in client.get("/api/catalog/ingest-plugins").json()}
    assert plugins["oak_d"]["available"] is False
    assert plugins["image_folder"]["kind"] == "bounded"


def test_datasets_con_disponibilidad(client):
    datasets = {d["id"]: d for d in client.get("/api/catalog/datasets").json()}
    assert datasets["demo"]["available"] is True
    assert datasets["roto"]["available"] is False
```

- [ ] **Step 2: Verificar que falla**

Run: `pytest tests/test_catalog_api.py -q`
Expected: FAIL con 404

- [ ] **Step 3: Implementación**

```python
# src/eovrt_media/service/routers/catalog.py
"""Catálogos del servicio: plugins de ingesta y datasets (Spec A §3.1)."""
from __future__ import annotations

from pathlib import Path

import yaml
from fastapi import APIRouter, Request

from eovrt_media.config.loader import find_plane_catalog_root, rebase_dataset_path
from eovrt_media.sources.registry import list_plugins

router = APIRouter(prefix="/api/catalog")


@router.get("/ingest-plugins")
def ingest_plugins() -> list[dict]:
    return list_plugins()


@router.get("/datasets")
def datasets(request: Request) -> list[dict]:
    settings = request.app.state.settings
    plane_root = find_plane_catalog_root(None, settings.catalog_root)
    datasets_dir = plane_root / "datasets"
    entries: list[dict] = []
    if datasets_dir.is_dir():
        for yaml_path in sorted(datasets_dir.glob("*.yaml")):
            data = yaml.safe_load(yaml_path.read_text()) or {}
            raw_path = data.get("path", "")
            resolved = rebase_dataset_path(raw_path, settings.datasets_root)
            entries.append(
                {
                    "id": yaml_path.stem,
                    "description": data.get("description"),
                    "path": resolved,
                    "available": Path(resolved).exists() if resolved else False,
                }
            )
    return entries
```

En `app.py`, incluir `catalog.router`.

- [ ] **Step 4: Verificar + suite completa**

Run: `pytest tests/test_catalog_api.py -q && pytest -q`
Expected: PASS todo.

- [ ] **Step 5: Commit**

```bash
git add src/eovrt_media/service/routers/catalog.py src/eovrt_media/service/app.py tests/test_catalog_api.py
git commit -m "feat(service): catalogos de plugins de ingesta y datasets"
```

---

### Task 16: Redacción de credenciales RTSP

**Files:**
- Modify: `src/eovrt_media/config/schemas.py` (`to_effective_dict`)
- Test: `tests/test_secret_redaction.py`

**Interfaces:**
- Produces: `redact_url_credentials(url: str) -> str` (módulo `schemas.py`, público); `RunConfig.to_effective_dict()` redacta `source.url` y `source.path` si contienen userinfo (`rtsp://user:pass@host` → `rtsp://***:***@host`). Cubre `effective_config.yaml` y todo lo derivado del dict efectivo.

- [ ] **Step 1: Test que falla**

```python
# tests/test_secret_redaction.py
from eovrt_media.config.schemas import RunConfig, redact_url_credentials

SET_INLINE = {"id": "t", "classes": [{"id": "p", "phrasings": {"default": ["p"]}}]}


def test_redact_userinfo():
    assert (
        redact_url_credentials("rtsp://admin:s3cret@10.0.0.5:554/stream")
        == "rtsp://***:***@10.0.0.5:554/stream"
    )


def test_redact_sin_credenciales_identidad():
    assert redact_url_credentials("rtsp://10.0.0.5/stream") == "rtsp://10.0.0.5/stream"


def test_effective_dict_redacta_source_url():
    config = RunConfig(
        run={},
        source={
            "type": "rtsp", "kind": "live",
            "path": "rtsp://u:p@cam/live", "url": "rtsp://u:p@cam/live",
        },
        model={"adapter": "mock"},
        prompts={"set_inline": SET_INLINE},
        rate_control={"policy": "bounded_freshness"},
    )
    data = config.to_effective_dict()
    assert "s3cret" not in str(data) and "u:p@" not in str(data)
    assert data["source"]["url"] == "rtsp://***:***@cam/live"
```

- [ ] **Step 2: Verificar que falla**

Run: `pytest tests/test_secret_redaction.py -q`
Expected: FAIL con `ImportError: redact_url_credentials`

- [ ] **Step 3: Implementación**

En `schemas.py` (arriba de `RunConfig`):

```python
import re

_URL_USERINFO = re.compile(r"//[^@/]+@")


def redact_url_credentials(url: str) -> str:
    """Redacta userinfo de URLs (rtsp://user:pass@host → rtsp://***:***@host)."""
    return _URL_USERINFO.sub("//***:***@", url)
```

En `RunConfig.to_effective_dict()`, después de `data = self.model_dump(...)`:

```python
        source_data = data.get("source")
        if isinstance(source_data, dict):
            for key in ("url", "path"):
                value = source_data.get(key)
                if isinstance(value, str) and "@" in value and "://" in value:
                    source_data[key] = redact_url_credentials(value)
```

- [ ] **Step 4: Verificar + suite completa**

Run: `pytest tests/test_secret_redaction.py -q && pytest -q`
Expected: PASS todo.

- [ ] **Step 5: Commit**

```bash
git add src/eovrt_media/config/schemas.py tests/test_secret_redaction.py
git commit -m "feat(config): redaccion de credenciales RTSP en config efectiva"
```

---

### Task 17: Eliminar el CLI y migrar utilitarios a `eovrt_media.tools`

**Files:**
- Create: `src/eovrt_media/tools/__init__.py`, `src/eovrt_media/tools/evaluate.py`, `src/eovrt_media/tools/inspect_runs.py`, `src/eovrt_media/tools/debug_run.py`
- Delete: `src/eovrt_media/cli.py`, `src/eovrt_media/runtime/two_node_local.py`, `tests/test_cli_two_node_local.py`, `scripts/run_grounding_dino_sample.sh`, `scripts/run_yoloe_sample.sh`
- Modify: `pyproject.toml` (quitar `[project.scripts]` y `typer`), `Makefile`, `CLAUDE.md`, `tests/test_cli_debug_run.py`, `tests/test_evaluate.py`, `tests/test_run_artifact_writer.py`

**Interfaces:**
- Produces: `python -m eovrt_media.tools.evaluate`, `python -m eovrt_media.tools.inspect_runs {inspect|compare}`, `python -m eovrt_media.tools.debug_run`. Las funciones internas conservan nombre y firma lógica de `cli.py` para que los tests las llamen directo.

- [ ] **Step 1: Migración mecánica de código (sin reescritura de lógica)**

Mover VERBATIM los cuerpos desde `src/eovrt_media/cli.py` (numeración actual):
- `evaluate` (cli.py:456-520) → `tools/evaluate.py`
- `inspect_run` (cli.py:302-364), `_collect_summaries` (cli.py:365-383), `compare_runs` (cli.py:385-454) → `tools/inspect_runs.py`
- `debug_run` (cli.py:156-201) → `tools/debug_run.py`

Regla de conversión por función: quitar el decorador `@app.command(...)`; convertir cada parámetro `x: T = typer.Option(default, ...)` / `typer.Argument(...)` en parámetro normal `x: T = default`; reemplazar `typer.echo(...)` por `print(...)` y `raise typer.Exit(code=N)` por `raise SystemExit(N)`; conservar rich `Console` si lo usan (rich sigue en deps). Copiar también los imports que cada cuerpo necesite.

Shell `main()` para cada archivo (ejemplo `inspect_runs.py`; `evaluate.py` y `debug_run.py` siguen el mismo esquema con sus propios argumentos, que se leen 1:1 de la firma migrada):

```python
def main() -> None:
    import argparse
    from pathlib import Path

    parser = argparse.ArgumentParser(prog="eovrt-inspect-runs")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_inspect = sub.add_parser("inspect")
    p_inspect.add_argument("run_dir", type=Path)
    p_compare = sub.add_parser("compare")
    p_compare.add_argument("runs_root", type=Path)
    args = parser.parse_args()
    if args.cmd == "inspect":
        inspect_run(args.run_dir)
    else:
        compare_runs(args.runs_root)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Migrar los tests que usaban CliRunner**

- `tests/test_evaluate.py`: reemplazar el único `runner.invoke(app, ["evaluate", ...])` por una llamada directa `from eovrt_media.tools.evaluate import evaluate; evaluate(<mismos argumentos>)` (los otros 12 tests del archivo no tocan el CLI). Quitar el import de `typer.testing`.
- `tests/test_run_artifact_writer.py`: reemplazar el `invoke` de `compare-runs` por `from eovrt_media.tools.inspect_runs import compare_runs; compare_runs(<runs_root>)`, capturando stdout con `capsys` si el test asertaba salida.
- `tests/test_cli_debug_run.py`: renombrar a `tests/test_debug_run.py`; reemplazar los 3 `invoke` por llamadas directas a `eovrt_media.tools.debug_run.debug_run(...)` con los mismos argumentos.
- Borrar `tests/test_cli_two_node_local.py` y `src/eovrt_media/runtime/two_node_local.py` (el spec elimina `run-two-node-local`; su equivalente Fase 2 es docker-compose). `tests/test_cli_two_node.py` NO se toca (no usa el CLI).

- [ ] **Step 3: Borrar CLI y limpiar empaquetado**

- Borrar `src/eovrt_media/cli.py`.
- `pyproject.toml`: eliminar la sección `[project.scripts]` completa y `"typer"` de `dependencies`.
- Borrar `scripts/run_grounding_dino_sample.sh` y `scripts/run_yoloe_sample.sh` (invocaban `eovrt-media`). `scripts/download_models.sh` NO se toca (nunca dependió del CLI).
- Nuevo `Makefile` (reemplazo completo):

```makefile
.PHONY: install lint test download-models serve smoke compare-runs

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
	EOVRT_MODEL_REF=$${EOVRT_MODEL_REF:-mock} \
	uvicorn --factory eovrt_media.service.app:create_app --host 0.0.0.0 --port 8080

smoke:
	curl -sf http://localhost:8080/healthz && curl -sf http://localhost:8080/readyz && echo OK

compare-runs:
	python -m eovrt_media.tools.inspect_runs compare runs
```

- `CLAUDE.md` del repo: reemplazar el bloque `## Commands` y la línea de "Execution path (single-host)" para reflejar: `make serve` + `POST /api/runs` (con ejemplo curl mínimo), `python -m eovrt_media.tools.{evaluate,inspect_runs,debug_run}`, y que el CLI `eovrt-media` ya no existe.

- [ ] **Step 4: Verificar**

Run: `pip install -e ".[dev]" && pytest -q && make lint && grep -rn "typer\|eovrt-media run" src tests Makefile | grep -v Binary; echo "grep-exit=$?"`
Expected: suite completa PASS; el grep no encuentra referencias vivas (exit 1).

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "refactor!: eliminar CLI Typer; utilitarios migrados a eovrt_media.tools"
```

---

### Task 18: Dockerfile + constraints + smoke de contenedor

**Files:**
- Create: `Dockerfile`, `.dockerignore`, `constraints.txt`
- Modify: `Makefile` (targets docker)

**Interfaces:**
- Produces: imagen única GPU (Fase 1) con healthcheck sobre `/readyz`, volúmenes para runs/datasets/pesos, arranque `uvicorn --factory`.

- [ ] **Step 1: Generar constraints**

Run (desde el venv del repo): `pip freeze --exclude-editable > constraints.txt`
Revisar que incluye `fastapi`, `uvicorn`, `torch` (versión CUDA local), `transformers`, `ultralytics` — commitear tal cual (reproducibilidad de imagen; Spec A §7.5).

- [ ] **Step 2: Escribir Dockerfile y .dockerignore**

```dockerfile
# Dockerfile — imagen única DBE (Fase 1, Spec A §3.3)
FROM nvidia/cuda:12.4.1-runtime-ubuntu22.04
ENV DEBIAN_FRONTEND=noninteractive PYTHONUNBUFFERED=1
RUN apt-get update && apt-get install -y --no-install-recommends \
        python3.11 python3.11-venv python3-pip libgl1 libglib2.0-0 curl \
    && rm -rf /var/lib/apt/lists/* \
    && python3.11 -m pip install --no-cache-dir --upgrade pip

WORKDIR /app
COPY pyproject.toml constraints.txt ./
COPY src ./src
COPY configs ./configs
RUN python3.11 -m pip install --no-cache-dir -c constraints.txt ".[gpu]"

ENV EOVRT_MODEL_REF=mock \
    EOVRT_MEDIA_CATALOG_ROOT=/app/configs \
    EOVRT_RUNS_DIR=/data/runs \
    EOVRT_DATASETS_ROOT=/data/datasets \
    HF_HOME=/data/weights
VOLUME ["/data/runs", "/data/datasets", "/data/weights"]
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=180s \
    CMD curl -sf http://localhost:8080/readyz || exit 1
CMD ["python3.11", "-m", "uvicorn", "--factory", "eovrt_media.service.app:create_app", \
     "--host", "0.0.0.0", "--port", "8080"]
```

```
# .dockerignore
.venv
runs
models
.git
__pycache__
*.pyc
docs
tests
```

Agregar al `Makefile`:

```makefile
docker-build:
	docker build -t eovrt-media-plane .

docker-run-mock:
	docker run --rm -p 8080:8080 -e EOVRT_MODEL_REF=mock \
	  -v $$(pwd)/runs:/data/runs eovrt-media-plane
```

- [ ] **Step 3: Smoke manual (sin GPU, modelo mock)**

Run:
```bash
make docker-build
make docker-run-mock &   # esperar el healthcheck
curl -sf localhost:8080/readyz          # → {"status":"ready","model":"mock"}
curl -sf localhost:8080/api/model
curl -sf localhost:8080/api/catalog/ingest-plugins
```
Expected: readyz 200 con `mock`; catálogos responden. Parar el contenedor al terminar. (La corrida GPU real con `EOVRT_MODEL_REF=grounding-dino/gdino-tiny`, `--gpus all` y datasets montados se valida en el host GPU — fuera de CI.)

- [ ] **Step 4: Suite + lint final del plan**

Run: `pytest -q && make lint`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add Dockerfile .dockerignore constraints.txt Makefile
git commit -m "feat(deploy): imagen GPU unica con healthchecks y constraints pinneados"
```

---

## Self-Review (hecho al escribir el plan)

- **Cobertura del spec (Fase 1, §10):** eliminar CLI con destino de utilitarios → Task 17; API control+WS+artefactos → Tasks 12-14; carga al startup sin recarga → Task 11; RunManager (409/stop/SIGTERM/watchdog) → Tasks 10-11; registro de plugins → Task 6; contenedor con datasets montados (`EOVRT_DATASETS_ROOT`) → Tasks 4, 18; prompts inline → Tasks 3, 5; retención → Task 11 (+DELETE Task 12); redacción de secretos → Task 16; contrato canónico y rechazo de `model` → Task 5 (+test de ruta en Task 12); `run_id` único → Task 10; historial desde RUNS_DIR → Task 10/12; pines → Task 18; tests con mock → todas. Fuera de alcance (correcto): §4.1 backends compilados, Fase 2 EBE, auth.
- **Sin placeholders:** el único paso no-código-completo es la migración verbatim de Task 17, anclada a líneas exactas de `cli.py` con regla de conversión mecánica.
- **Consistencia de tipos/nombres:** `ServiceSettings`, `RunRequest/to_raw_run_config`, `execute_run/RunControl`, `EventBroadcaster/Subscriber`, `RunManager.start_run/get/list_runs/subscribe` usados con la misma firma en tasks posteriores.
