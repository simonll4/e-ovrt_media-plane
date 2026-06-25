# Infra de Deploy del Media Plane — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Organizar la infraestructura de despliegue two-node en un directorio `deploy/` bien documentado, con el Nodo A edge genuinamente liviano (sin torch).

**Architecture:** Refactor prerequisito de lazy imports para que el Nodo A slim arranque sin torch, seguido de la estructura `deploy/` (Dockerfiles migrados, compose parametrizado por `.env`, configs de ejemplo, README) y validación end-to-end del compose con GPU.

**Tech Stack:** Python 3.11, Docker + Compose, ZeroMQ (pyzmq), nvidia-container-toolkit.

## Alineación posterior a la validación E2E

La validación detectó que el compose único sólo representa correctamente el modo local:
`node-b.depends_on: node-a` iniciaba un productor no deseado en el host GPU. La entrega
final añade `deploy/docker-compose.node-a.yml` y `deploy/docker-compose.node-b.yml`
para el modo distribuido, manteniendo `deploy/docker-compose.yml` como stack local.
Además, Nodo B fija el commit de CLIP y precarga `mobileclip2_b.ts` durante el build;
por eso no depende de Internet en el primer arranque.

## Global Constraints

- **Un único commit final**: por pedido del usuario, NO hay commits intermedios. Cada task termina en verificación (tests/lint/validate), no en commit. El último task ejecuta el único `git commit` con todo el workstream.
- **Sin secretos versionados**: los configs con IPs reales o credenciales nunca se commitean (`deploy/configs/*.yaml` gitignored salvo `*.example.yaml`).
- **No romper la suite**: `pytest -q` completo y `ruff check src tests` deben quedar verdes al final.
- **Repos siblings**: el media-plane asume `../e-ovrt_datasets` como hermano en disco (per CLAUDE.md).
- **Nodo A sin GPU**: imagen `python:3.11-slim`, extra `edge` (sin torch/transformers/ultralytics). Nodo B con GPU: `nvidia/cuda:12.6.3-cudnn-runtime-ubuntu24.04`, extra `gpu`.

---

### Task 1: Refactor lazy imports de torch

**Files:**
- Modify: `src/eovrt_media/models/runtime_utils.py`
- Modify: `src/eovrt_media/models/grounding_dino_adapter.py`
- Modify: `src/eovrt_media/models/__init__.py`
- Test: `tests/test_edge_imports_without_torch.py`

**Interfaces:**
- Consumes: nada nuevo.
- Produces: `create_adapter()` y `eovrt_media.runtime.two_node` importables sin `torch` instalado. Firmas sin cambios: `resolve_device(requested: str, cuda_available: bool | None = None) -> str`, `create_adapter(model_config: ModelSection) -> BaseDetectorAdapter`.

- [x] **Step 1: Write the failing guard test**

Crear `tests/test_edge_imports_without_torch.py`:

```python
"""Guard: el Nodo A edge (sin torch) debe poder importar el pipeline two-node."""
import builtins

import pytest


@pytest.fixture
def block_torch(monkeypatch):
    real_import = builtins.__import__

    def _blocked(name, *args, **kwargs):
        if name == "torch" or name.startswith("torch."):
            raise ImportError("torch bloqueado (simulando node-a edge slim)")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _blocked)
    # Purga módulos ya importados que arrastran torch, para forzar re-import limpio
    for mod in list(__import__("sys").modules):
        if mod.startswith("eovrt_media.models") or mod.startswith("eovrt_media.runtime"):
            monkeypatch.delitem(__import__("sys").modules, mod, raising=False)


def test_two_node_importable_without_torch(block_torch):
    from eovrt_media.runtime import two_node  # noqa: F401


def test_create_adapter_yoloe_instantiable_without_torch(block_torch):
    # El Nodo A instancia el adapter solo para leer input_spec; nunca llama load()
    from eovrt_media.config.schemas import ModelSection

    model_cfg = ModelSection(adapter="yoloe", weights="yoloe-26s-seg.pt", device="cpu")
    from eovrt_media.models import create_adapter

    adapter = create_adapter(model_cfg)
    assert adapter.input_spec.target_size == (640, 640)
```

- [x] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_edge_imports_without_torch.py -v`
Expected: FAIL — `ImportError: torch bloqueado` al importar `two_node` (los imports eager arrastran torch).

- [x] **Step 3: Lazy import en `runtime_utils.py`**

Quitar `import torch` del nivel de módulo (línea 7) y moverlo dentro de `resolve_device`:

```python
"""Helpers de runtime para adaptadores de modelo (device, fp16, warmup)."""
from __future__ import annotations

import logging

import numpy as np

logger = logging.getLogger(__name__)


def resolve_device(requested: str, cuda_available: bool | None = None) -> str:
    """Normaliza el device: degrada a cpu si se pide cuda y no hay GPU."""
    if cuda_available is None:
        import torch

        cuda_available = torch.cuda.is_available()
    if requested.startswith("cuda") and not cuda_available:
        logger.warning("device=%s solicitado sin CUDA disponible; usando cpu", requested)
        return "cpu"
    return requested


def should_use_half(device: str, half_precision: bool) -> bool:
    """fp16 solo cuando el flag está activo y el device es CUDA."""
    return bool(half_precision) and device.startswith("cuda")


def make_warmup_image(target_size: tuple[int, int]) -> np.ndarray:
    """Imagen negra uint8 (H, W, 3) para el warmup del modelo."""
    h, w = target_size
    return np.zeros((h, w, 3), dtype=np.uint8)
```

- [x] **Step 4: Lazy import en `grounding_dino_adapter.py`**

Quitar `import torch` (línea 11) y `from transformers import AutoModelForZeroShotObjectDetection, AutoProcessor` (línea 13) del nivel de módulo. Agregar `import torch` y el import de transformers al inicio del cuerpo de `load()`, e `import torch` local al inicio del método de inferencia (el que usa `torch.autocast`/`torch.no_grad`) y de `close()`.

En `load()`, primera línea del cuerpo:

```python
    def load(self) -> None:
        import torch
        from transformers import AutoModelForZeroShotObjectDetection, AutoProcessor
        # ... resto del método sin cambios (usa AutoProcessor, AutoModel..., torch)
```

En el método que hace autocast/no_grad (alrededor de las líneas 112-116), agregar como primera línea del método:

```python
        import torch
```

En `close()` (alrededor de líneas 174-175), agregar como primera línea del método:

```python
        import torch
```

- [x] **Step 5: Lazy import en `models/__init__.py`**

Quitar las líneas 9-10 (imports eager de los adapters pesados) y moverlos adentro de `create_adapter`. Quitarlos de `__all__`:

```python
"""Módulo de adaptadores de modelos del plano de medios E-OVRT."""

from __future__ import annotations

from typing import TYPE_CHECKING

from eovrt_media.models.base import BaseDetectorAdapter
from eovrt_media.models.mock_detector import MockDetectorAdapter

if TYPE_CHECKING:
    from eovrt_media.config import ModelSection


def create_adapter(model_config: ModelSection) -> BaseDetectorAdapter:
    """Crea un adaptador de modelo según la configuración de corrida.

    Args:
        model_config: Sección 'model' de la configuración.

    Returns:
        Instancia del adaptador correspondiente (sin cargar pesos aún).
    """
    adapter_name = model_config.adapter or model_config.name

    if not adapter_name:
        raise ValueError("No se especificó 'adapter' o 'name' en la configuración del modelo.")

    adapter_name = adapter_name.lower().strip()

    if adapter_name == "mock":
        return MockDetectorAdapter()

    elif adapter_name in ("grounding_dino", "grounding_dino_hf"):
        from eovrt_media.models.grounding_dino_adapter import GroundingDinoHFAdapter

        return GroundingDinoHFAdapter(
            model_id=model_config.model_id or "IDEA-Research/grounding-dino-tiny",
            device=model_config.device,
            box_threshold=model_config.box_threshold,
            text_threshold=model_config.text_threshold,
            local_dir=model_config.local_dir,
            half_precision=model_config.runtime.half_precision,
            warmup=model_config.runtime.warmup,
        )

    elif adapter_name in ("yoloe", "yoloe_ultralytics"):
        from eovrt_media.models.yoloe_adapter import YOLOEUltralyticsAdapter

        return YOLOEUltralyticsAdapter(
            weights=model_config.weights or "yoloe-26s-seg.pt",
            device=model_config.device,
            confidence_threshold=model_config.confidence_threshold,
            iou_threshold=model_config.iou_threshold,
            image_size=model_config.image_size,
            half_precision=model_config.runtime.half_precision,
            warmup=model_config.runtime.warmup,
        )

    else:
        raise ValueError(
            f"Adaptador '{adapter_name}' no soportado. "
            f"Opciones: mock, grounding_dino, yoloe"
        )


__all__ = [
    "BaseDetectorAdapter",
    "MockDetectorAdapter",
    "create_adapter",
]
```

- [x] **Step 6: Run guard test + full suite**

Run: `pytest tests/test_edge_imports_without_torch.py -v && make test && make lint`
Expected: guard test PASS; suite y Ruff limpios.

---

### Task 2: `.dockerignore` y reglas gitignore

**Files:**
- Create: `.dockerignore` (raíz del repo)
- Modify: `.gitignore` (raíz del repo)

**Interfaces:**
- Consumes: nada.
- Produces: build context mínimo para Docker; `deploy/configs/*.yaml` ignorado salvo `*.example.yaml`.

- [x] **Step 1: Crear `.dockerignore` en la raíz**

```
.venv/
venv/
runs/
models/
.git/
**/__pycache__/
*.py[cod]
.pytest_cache/
.ruff_cache/
.mypy_cache/
.superpowers/
docs/
tests/
*.egg-info/
dist/
build/
```

- [x] **Step 2: Agregar reglas a `.gitignore`**

Agregar al final del `.gitignore` existente:

```
# Configs de deploy con endpoints/IPs reales (los *.example.yaml sí se versionan)
deploy/configs/*.yaml
!deploy/configs/*.example.yaml
```

- [x] **Step 3: Verificar las reglas de ignore**

Run: `git check-ignore deploy/configs/two_node_a.yaml deploy/configs/two_node_a.example.yaml; echo "---"; ls .dockerignore`
Expected: la primera ruta se imprime (ignorada), la segunda NO (no ignorada por la regla `!`), y `.dockerignore` existe.

---

### Task 3: Migrar Dockerfiles a `deploy/docker/`

**Files:**
- Create: `deploy/docker/Dockerfile.node-a`
- Create: `deploy/docker/Dockerfile.node-b`

**Interfaces:**
- Consumes: extras `edge` y `gpu` de `pyproject.toml`.
- Produces: imágenes node-a (edge) y node-b (GPU) construibles con context = raíz del repo.

- [x] **Step 1: Crear `deploy/docker/Dockerfile.node-a`**

```dockerfile
# Nodo A — ingesta + normalización + servidor ZeroMQ. Sin GPU.
FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 libglib2.0-0 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir -e ".[edge]"

ENTRYPOINT ["eovrt-media", "run-producer"]
CMD ["--config", "/configs/two_node_a.yaml"]
```

- [x] **Step 2: Crear `deploy/docker/Dockerfile.node-b`**

```dockerfile
# Nodo B — inferencia + postproceso + artefactos. Requiere GPU NVIDIA.
FROM nvidia/cuda:12.6.3-cudnn-runtime-ubuntu24.04

RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 python3-pip python3-venv libgl1 libglib2.0-0 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml ./
COPY src ./src
RUN python3 -m venv /opt/venv && /opt/venv/bin/pip install --no-cache-dir -e ".[gpu]"
ENV PATH="/opt/venv/bin:${PATH}"

ENTRYPOINT ["eovrt-media", "run-consumer"]
CMD ["--config", "/configs/two_node_b.yaml"]
```

- [x] **Step 3: Verificar que los Dockerfiles existen**

Run: `test -f deploy/docker/Dockerfile.node-a && test -f deploy/docker/Dockerfile.node-b && echo "dockerfiles OK"`
Expected: `dockerfiles OK`. (El build completo se valida en Task 7.)

---

### Task 4: Configs de ejemplo two-node

**Files:**
- Create: `deploy/configs/two_node_a.example.yaml`
- Create: `deploy/configs/two_node_b.example.yaml`

**Interfaces:**
- Consumes: catálogos `model.ref: yoloe/yoloe-26s`, `prompts.ref: cr01_cr02_bench_v2`.
- Produces: configs válidos para test local en compose. A bindea `0.0.0.0:5555`, B conecta `node-a:5555`. El source (dataset) se lee en el Nodo A desde `/datasets/...` (montado por compose).

- [x] **Step 1: Crear `deploy/configs/two_node_a.example.yaml`**

```yaml
### Nodo A (edge) — ejemplo para test local two-node en compose.
### Bindea el REP server a 0.0.0.0 para que node-b conecte vía la red bridge.
### El dataset se monta en /datasets (ver docker-compose.yml).
run:
  scenario: EBE
  name: ebe_node_a
  description: "Nodo A: ingesta + normalización + servidor ZeroMQ (test local)."

source:
  type: image_folder
  path: /datasets/construction_site_safety/valid/images

model:
  ref: yoloe/yoloe-26s

prompts:
  ref: cr01_cr02_bench_v2
  active_ids: [person, helmet, vest, bare_head]

topology:
  mode: two_node

transport:
  backend: network
  endpoint: "tcp://0.0.0.0:5555"
  heartbeat_endpoint: "tcp://0.0.0.0:5556"
  payload_format: uint8_rgb
  compression:
    codec: jpeg
    quality: 90
```

- [x] **Step 2: Crear `deploy/configs/two_node_b.example.yaml`**

```yaml
### Nodo B (GPU) — ejemplo para test local two-node en compose.
### Conecta al REP server de node-a vía el DNS interno de compose (node-a:5555).
### Para deploy real: copiar a two_node_b.yaml y cambiar endpoint al IP del edge.
run:
  scenario: EBE
  name: ebe_node_b
  description: "Nodo B: cliente ZeroMQ + inferencia + artefactos (test local)."

source:
  type: image_folder
  path: /datasets/construction_site_safety/valid/images

model:
  ref: yoloe/yoloe-26s
  device: cuda:0
  runtime:
    half_precision: true
    warmup: true

prompts:
  ref: cr01_cr02_bench_v2
  active_ids: [person, helmet, vest, bare_head]

topology:
  mode: two_node

transport:
  backend: network
  endpoint: "tcp://node-a:5555"
  heartbeat_endpoint: "tcp://node-a:5556"
  payload_format: uint8_rgb
  compression:
    codec: jpeg
    quality: 90
```

- [x] **Step 2b: Renombrar a config activo para validar localmente**

Los `*.example.yaml` se validan copiándolos a la forma activa (las refs de catálogo se resuelven contra el repo, no contra `/configs`):

Run: `source .venv/bin/activate && cp deploy/configs/two_node_a.example.yaml /tmp/node_a.yaml && cp deploy/configs/two_node_b.example.yaml /tmp/node_b.yaml && eovrt-media validate-config --config /tmp/node_a.yaml && eovrt-media validate-config --config /tmp/node_b.yaml`
Expected: ambos imprimen `✓ Configuración válida`. (El `path` `/datasets/...` no se verifica en validate-config; se monta en runtime — Task 7.)

---

### Task 5: docker-compose + .env.example, eliminar docker/ viejo

**Files:**
- Create: `deploy/docker-compose.yml`
- Create: `deploy/.env.example`
- Delete: `docker/Dockerfile.node-a`, `docker/Dockerfile.node-b`, `docker/docker-compose.yml`, directorio `docker/`

**Interfaces:**
- Consumes: Dockerfiles de `deploy/docker/` (Task 3), configs de `deploy/configs/` (Task 4).
- Produces: stack two-node levantable con `docker compose up` desde `deploy/`.

- [x] **Step 1: Crear `deploy/docker-compose.yml`**

> **Borrador histórico.** El bloque siguiente es la propuesta inicial, retenida para trazabilidad.
> El artefacto materializado y validado es [`deploy/docker-compose.yml`](../../../deploy/docker-compose.yml):
> monta `../configs` en `/app/configs` y `./configs` en `/app/deploy-configs`; los manifiestos
> independientes y el endpoint TCP/5556 se documentan en el plan de alineación y en `deploy/README.md`.

```yaml
# Despliegue de dos nodos del plano de medios.
# Nodo A (edge) y Nodo B (GPU) comparten una red puente para el canal ZeroMQ.
# Variables: copiar .env.example -> .env. Para test local, los defaults apuntan
# a los *.example.yaml y al dataset cross-repo montado en /datasets.
services:
  node-a:
    build:
      context: ..
      dockerfile: deploy/docker/Dockerfile.node-a
    command: ["--config", "${NODE_A_CONFIG:-/configs/two_node_a.example.yaml}"]
    networks: [media-plane]
    volumes:
      - ./configs:/configs:ro
      - ../../e-ovrt_datasets/datasets/raw:/datasets:ro
    expose: ["5555", "5556"]

  node-b:
    build:
      context: ..
      dockerfile: deploy/docker/Dockerfile.node-b
    command: ["--config", "${NODE_B_CONFIG:-/configs/two_node_b.example.yaml}"]
    networks: [media-plane]
    volumes:
      - ./configs:/configs:ro
      - ../models:/app/models:ro
      - ../runs:/app/runs
    depends_on: [node-a]
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: 1
              capabilities: [gpu]

networks:
  media-plane:
    driver: bridge
```

- [x] **Step 2: Crear `deploy/.env.example`**

> **Borrador histórico.** Los defaults finales usan `/app/deploy-configs/...`; consultar el
> archivo materializado [`deploy/.env.example`](../../../deploy/.env.example).

```bash
# Copiar a .env y ajustar. Selecciona qué config monta cada nodo.
# Test local: dejar los defaults (apuntan a los *.example.yaml).
# Deploy real: apuntar a un config propio (p. ej. /configs/two_node_b.yaml) y
# editar su transport.endpoint al IP real del edge.
NODE_A_CONFIG=/configs/two_node_a.example.yaml
NODE_B_CONFIG=/configs/two_node_b.example.yaml
```

- [x] **Step 3: Eliminar el directorio `docker/` viejo de la raíz**

Run: `git rm -r docker/ 2>/dev/null || rm -rf docker/; ls docker/ 2>&1 | head -1`
Expected: `docker/` ya no existe (`No such file or directory`).

- [x] **Step 4: Verificar que el compose parsea**

Run: `cd deploy && docker compose config >/dev/null && echo "compose OK"; cd ..`
Expected: `compose OK` (sintaxis e interpolación válidas; `docker compose config` no construye nada).

---

### Task 6: README de deploy y redirección del doc previo

**Files:**
- Create: `deploy/README.md`
- Modify: `docs/deployment/two-node-docker.md` (reemplazar por redirección)

**Interfaces:**
- Consumes: estructura de Tasks 3-5.
- Produces: documentación única de deploy.

- [x] **Step 1: Crear `deploy/README.md`**

> **Borrador histórico.** La guía final materializada, con DBE/EBE en ambas topologías, TCP/5555,
> TCP/5556 y el contrato FP16, es [`deploy/README.md`](../../../deploy/README.md). El bloque se
> conserva para registrar el punto de partida del plan, no como instrucción operativa.

```markdown
# Deploy del Media Plane

Infraestructura de despliegue del plano de medios. El **single-host (DBE)** corre
nativo con venv; el **two-node (EBE)** se empaqueta en dos imágenes Docker.

## Single-host (DBE) — nativo

```bash
python3.11 -m venv .venv && source .venv/bin/activate && pip install -e ".[gpu,dev]"
eovrt-media run --config configs/runs/<file>.yaml
```

## Two-node (EBE) — Docker

- **node-a** (edge, sin GPU): ingesta, rate control, normalización, servidor ZeroMQ.
- **node-b** (GPU): cliente ZeroMQ, inferencia OVD, postproceso, artefactos.

### Requisitos

- Docker + plugin Compose.
- En el host de node-b: GPU NVIDIA + [nvidia-container-toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html).
- **WSL2**: CUDA en Docker depende del driver NVIDIA del host Windows. Verificar:
  `docker run --rm --gpus all nvidia/cuda:12.6.3-cudnn-runtime-ubuntu24.04 nvidia-smi`.

### Estructura

```
deploy/
  docker-compose.yml       Stack two-node (parametrizado por .env)
  .env.example             Plantilla: qué config monta cada nodo
  docker/                  Dockerfile.node-a (edge), Dockerfile.node-b (GPU)
  configs/                 two_node_{a,b}.example.yaml (versionados, sin IPs reales)
```

### Quickstart — test local (un host)

Levanta ambos nodos en la red bridge; node-b resuelve `node-a` por DNS interno.

```bash
cd deploy
cp .env.example .env          # defaults apuntan a los *.example.yaml
docker compose build
docker compose up
```

Requiere el repo `e-ovrt_datasets` como hermano en disco (se monta en `/datasets`).
Los artefactos quedan en `runs/` del host.

### Quickstart — deploy real (dos hosts)

En el **host edge**:

```bash
cd deploy && docker compose -f docker-compose.node-a.yml up
```

En el **host GPU**, copiar el config de B y apuntar el endpoint al IP del edge:

```bash
cd deploy/configs
cp two_node_b.example.yaml two_node_b.yaml
# editar two_node_b.yaml:
#   transport.endpoint: "tcp://<ip-edge>:5555"
#   transport.heartbeat_endpoint: "tcp://<ip-edge>:5556"
cd ..
echo "NODE_B_CONFIG=/configs/two_node_b.yaml" > .env
docker compose -f docker-compose.node-b.yml up
```

### Variables `.env`

| Variable        | Default                              | Descripción                          |
|-----------------|--------------------------------------|--------------------------------------|
| `NODE_A_CONFIG` | `/configs/two_node_a.example.yaml`   | Config montado en node-a             |
| `NODE_B_CONFIG` | `/configs/two_node_b.example.yaml`   | Config montado en node-b             |

El endpoint NO se parametriza por `.env` (el loader no soporta env vars); vive dentro
del YAML de config. `.env` solo selecciona qué archivo se monta.

### Fricciones conocidas

- Las imágenes CUDA/PyTorch son grandes; el primer build de node-b es lento.
- OAK-D Pro PoE en contenedor queda pendiente hasta disponer del hardware.
```

- [x] **Step 2: Reemplazar `docs/deployment/two-node-docker.md` por una redirección**

```markdown
# Despliegue de dos nodos con Docker

> Movido. La guía de deploy vive ahora en [`deploy/README.md`](../../deploy/README.md).
```

- [x] **Step 3: Verificar enlaces y contenido**

Run: `test -f deploy/README.md && grep -q "deploy/README.md" docs/deployment/two-node-docker.md && echo "docs OK"`
Expected: `docs OK`.

---

### Task 7: Validación end-to-end y commit único

**Files:**
- ninguno nuevo (validación + commit del workstream completo)

**Interfaces:**
- Consumes: todo lo anterior.
- Produces: stack validado + único commit.

- [x] **Step 1: Verificar GPU disponible en Docker (WSL2)**

Run: `docker run --rm --gpus all nvidia/cuda:12.6.3-cudnn-runtime-ubuntu24.04 nvidia-smi | head -5`
Expected: tabla de `nvidia-smi` con la GPU. Si falla, el deploy real de node-b no funcionará (registrar y detener — es prerequisito de host, no del código).

- [x] **Step 2: Build de ambas imágenes**

Run: `cd deploy && docker compose build 2>&1 | tail -10; cd ..`
Expected: build de node-a y node-b sin error (`Successfully built` / `FINISHED`).

- [x] **Step 3: Corrida test local two-node**

Run: `cd deploy && cp .env.example .env && docker compose up --abort-on-container-exit 2>&1 | tail -20; cd ..`
Expected: node-b carga el modelo con `device=cuda`, procesa frames y termina; node-a sirve los frames y cierra. Sin tracebacks.

- [x] **Step 4: Verificar artefactos**

Run: `ls -t runs/ | head -1 | xargs -I{} python3 -c "import json; d=json.load(open('runs/{}/summary.json')); print('processed:', d['units_processed'], 'failed:', d['units_failed'], 'backend:', d['run_descriptor']['transport']['backend'])"`
Expected: `units_processed: 114, units_failed: 0, backend: network` (consistente con el Paso 2 nativo).

- [x] **Step 5: Suite + lint verdes**

Run: `source .venv/bin/activate && make test && make lint`
Expected: suite vigente passing; ruff limpio.

- [x] **Step 6: Commit único del workstream**

```bash
git add -A
git commit -m "feat(deploy): organizar infra de deploy two-node en deploy/ + lazy imports edge

- Refactor lazy imports de torch (runtime_utils, grounding_dino_adapter,
  models/__init__) para que el Nodo A edge slim arranque sin torch
- Estructura deploy/: docker-compose.yml parametrizado por .env, Dockerfiles
  migrados a deploy/docker/, configs de ejemplo two_node_{a,b}, README único
- .dockerignore en raíz + gitignore para deploy/configs/*.yaml
- Reemplaza docker/ raíz y docs/deployment/two-node-docker.md (redirección)
- Validado: build OK, compose up two-node con GPU, 114/114 procesadas sin error"
```

---

## Notas de ejecución

- **Tasks 1-6 NO commitean** (Global Constraints: commit único final). El subagente/ejecutor debe omitir cualquier paso de commit hasta el Step 6 del Task 7.
- Si en Task 7 el host no tiene GPU en Docker (WSL2 sin driver), registrar el bloqueo: build y compose-config se pueden validar igual, pero la corrida con `device=cuda` requiere la GPU. Reportar al usuario antes de forzar.

### Registro — 2026-06-24

- El commit `42fcfd2` materializó Tasks 1–6 y el commit único de este workstream.
- La validación posterior registró Docker Engine 29.5.3, una NVIDIA GeForce RTX 4060 disponible
  para Docker, build de ambas imágenes y el stack local con 114 unidades procesadas, 0 fallidas,
  193 detecciones y `cuda:0`.
- La verificación local actual de Python pasa con la suite completa vigente; los manifests locales y de dos hosts
  incluyen también el endpoint de heartbeat TCP/5556 añadido después de este plan inicial.
