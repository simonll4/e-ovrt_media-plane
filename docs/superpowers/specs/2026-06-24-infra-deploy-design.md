# Diseño: Infra de deploy del Media Plane

**Fecha:** 2026-06-24
**Rama:** `feat/ebe-fuente-viva`
**Estado:** implementado y verificado

## 1. Propósito

Organizar la infraestructura de despliegue del plano de medios en un directorio
dedicado (`deploy/`), bien documentado, que cubra la topología **two-node** (EBE
distribuido) con Docker. Completa y reemplaza la infra parcial actual (`docker/` en
la raíz + `docs/deployment/two-node-docker.md`), que está incompleta y sin validar.

El single-host (DBE) **no se dockeriza**: sigue siendo ejecución nativa con venv,
documentada en el README de deploy. Decisión YAGNI — el venv ya cubre desarrollo y
evaluación; Docker solo aporta valor donde empaqueta nodos heterogéneos (edge sin GPU,
server con GPU).

## 2. Alcance

**Incluye:**
- **Refactor prerequisito — lazy imports de torch** (ver §12). Sin esto el Nodo A edge
  no arranca. Es la única excepción a "infra pura": un refactor acotado y testeable.
- Estructura `deploy/` con Dockerfiles, compose, configs de ejemplo y README.
- `.dockerignore` en la raíz del repo (excluye `.venv/`, `runs/`, `models/`, `.git`).
- Configs versionables `two_node_{a,b}.example.yaml` sin secretos ni endpoints concretos.
- Parametrización por `.env`: selección del archivo de config a montar en cada nodo.
- Un compose de integración local y dos manifiestos host-específicos para el deploy
  real de dos hosts.
- Migración de `docker/` raíz → `deploy/docker/` y reemplazo del doc de deployment.
- Validación final: levantar el compose y verificar GPU en Nodo B (WSL2).

**Excluye (fuera de scope):**
- Single-host Docker (YAGNI; venv nativo).
- La prueba de esta entrega contra una cámara RTSP física; `RtspSource` y los manifiestos
  sí soportan RTSP. La única integración de fuente diferida es OAK-D Pro PoE, que requiere
  hardware y SDK DepthAI.
- Override de endpoint por variable de entorno en el config loader. No forma parte del
  contrato: los endpoints se definen en los YAML montados por host.

## 3. Estructura de directorios

```
deploy/
  README.md                    Guía única de deploy (índice + quickstart + tabla .env)
  docker-compose.yml           Integración local: two-node en red bridge
  docker-compose.node-a.yml    Host edge: sólo productor, publica TCP/5555
  docker-compose.node-b.yml    Host GPU: sólo consumidor, sin dependencias locales
  .env.example                 Plantilla de variables (qué config monta cada nodo)
  docker/
    Dockerfile.node-a          Edge, sin GPU (migrado)
    Dockerfile.node-b          GPU NVIDIA (migrado)
  configs/
    two_node_a.example.yaml    Config versionado del Nodo A (sin secretos)
    two_node_b.example.yaml    Config versionado del Nodo B (sin secretos)
.dockerignore                  En la RAÍZ del repo (restricción de Docker: debe estar
                               en el root del build context)
```

`docker/` en la raíz se elimina tras migrar su contenido. `docs/deployment/two-node-docker.md`
se reemplaza por un stub de una línea que apunta a `deploy/README.md`.

## 4. Manifiestos Compose: rutas y parametrización

El compose local vive en `deploy/docker-compose.yml`. El build context es la raíz del
repo (necesita `src/` y `pyproject.toml`); el Dockerfile se referencia relativo al
context. Es el único manifiesto que define la red bridge y `depends_on`, porque ambos
servicios corren en la misma máquina.

El deploy real usa manifiestos independientes: `docker-compose.node-a.yml` define sólo
el productor y publica `5555:5555`; `docker-compose.node-b.yml` define sólo el
consumidor con GPU. Este último no contiene `depends_on`, no inicia un productor local
y su endpoint se configura hacia el host edge en YAML.

```yaml
services:
  node-a:
    build:
      context: ..
      dockerfile: deploy/docker/Dockerfile.node-a
    command: ["--config", "${NODE_A_CONFIG:-/configs/two_node_a.yaml}"]
    networks: [media-plane]
    volumes:
      - ./configs:/configs:ro
    expose: ["5555"]

  node-b:
    build:
      context: ..
      dockerfile: deploy/docker/Dockerfile.node-b
    command: ["--config", "${NODE_B_CONFIG:-/configs/two_node_b.yaml}"]
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

`command:` reemplaza el `CMD` del Dockerfile y se concatena al `ENTRYPOINT`
(`eovrt-media run-producer` / `run-consumer`), resultando en
`eovrt-media run-producer --config <val>`. La interpolación `${VAR:-default}` la
resuelve compose desde el `.env` del directorio `deploy/`.

## 5. Configs versionables y modos de uso

Los `*.example.yaml` en `deploy/configs/` son plantillas commiteables: `topology.mode:
two_node`, `transport.backend: network`, `compression`, `model.ref`, `prompts`. El
endpoint del ejemplo usa el **DNS interno de compose** (`tcp://node-a:5555`), que no es
un secreto y funciona out-of-the-box para test local. Lo que los examples **no** llevan
es IPs reales de deploy ni credenciales.

**Diferencia clave entre modos: el endpoint.**

- **Test local** (un host): `docker compose up` levanta A+B en la red bridge. El config
  de B usa `transport.endpoint: tcp://node-a:5555` (DNS interno de compose). Funciona con
  los examples sin editar. Es la versión containerizada del Paso 2 ya validado de forma
  nativa.
- **Deploy real** (dos hosts): en el edge,
  `docker compose -f docker-compose.node-a.yml up`; en el GPU,
  `docker compose -f docker-compose.node-b.yml up` con un config cuyo `endpoint` apunta
  al IP real del edge (`tcp://<ip-edge>:5555`).

**Flujo de configs (patrón `.example`):**

1. Los `*.example.yaml` se commitean y sirven tal cual para test local.
2. Para deploy real, el usuario copia: `cp two_node_b.example.yaml two_node_b.yaml` y
   edita el endpoint al IP del edge.
3. `.gitignore` ignora `deploy/configs/*.yaml` pero **no** `deploy/configs/*.example.yaml`
   (mismo patrón que `.env` / `.env.example`), evitando commitear IPs reales.
4. El `.env` selecciona qué archivo monta cada nodo vía `NODE_{A,B}_CONFIG`
   (default: `two_node_{a,b}.yaml`). Para test local sin copiar nada, el `.env.example`
   apunta `NODE_{A,B}_CONFIG` directo a los `*.example.yaml`.

## 6. Dependencias de Nodo B sin descarga en runtime

El Dockerfile de Nodo B fija el repositorio `ultralytics/CLIP` a un SHA de commit y
materializa `mobileclip2_b.ts` durante el build mediante `MobileCLIPTS` en `/app`.
Ultralytics encuentra ese asset desde su directorio de trabajo al ejecutar
`set_classes`, por lo que el primer arranque no descarga MobileCLIP. Los pesos YOLOE
permanecen como volumen explícito bajo `../models/`.

## 7. Decisión sobre el endpoint (registro)

El config loader **no** soporta variables de entorno ni interpolación; `transport.endpoint`
se lee directo del YAML. Por lo tanto el endpoint **no** se parametriza por `.env` —
lo que `.env` selecciona es *qué archivo de config* monta cada nodo.

Alternativa descartada para este workstream: agregar `os.path.expandvars` (o resolución
de `${VAR}`) en el loader para permitir `endpoint: ${EOVRT_ENDPOINT}`. Es más ergonómico
para ops pero implica código de aplicación + tests, fuera del scope de infra. Queda como
**follow-up opcional** si editar el YAML por deploy resulta molesto en la práctica.

## 8. `.dockerignore`

En la raíz del repo (Docker exige que esté en el root del build context). Excluye:

```
.venv/
runs/
models/
.git/
**/__pycache__/
*.pyc
.superpowers/
docs/
tests/
```

Adicionalmente, regla en el `.gitignore` del repo para los configs de deploy:

```
deploy/configs/*.yaml
!deploy/configs/*.example.yaml
```

Objetivo: build context mínimo. Sin esto, el context arrastra pesos de modelos y el venv,
haciendo el build lento y las imágenes innecesariamente grandes.

## 9. README de deploy

`deploy/README.md`, secciones:
- **Requisitos**: Docker + Compose; en Nodo B, GPU NVIDIA + nvidia-container-toolkit;
  nota WSL2 (CUDA depende del driver del host Windows; verificar con
  `docker run --rm --gpus all nvidia/cuda:12.6.3-cudnn-runtime-ubuntu24.04 nvidia-smi`).
- **Single-host (DBE)**: ejecución nativa con venv — `eovrt-media run --config ...`.
- **Quickstart test local two-node**: copiar `.env.example`, `docker compose up`.
- **Quickstart deploy real two-node**: configs por host, endpoint al IP del edge y
  manifiestos `docker-compose.node-a.yml` / `docker-compose.node-b.yml` por separado.
- **Tabla de variables `.env`**: `NODE_A_CONFIG`, `NODE_B_CONFIG`.
- **Fricciones conocidas**: builds CUDA/PyTorch grandes; OAK-D PoE pendiente.

## 10. Validación (criterio de éxito)

1. `docker compose build` completa sin error para ambos nodos.
2. `docker compose up` levanta A+B; el Nodo B detecta GPU (verificable en logs de carga
   del modelo: `device=cuda`).
3. Una corrida test local two-node produce `runs/<run_id>/` con `detections.jsonl` y
   `summary.json` poblados, con `units_failed: 0`.
4. Resultados consistentes con el Paso 2 nativo (mismo dataset, mismo modelo).
5. `make test` y `make lint` siguen verdes (la migración no debe romper nada).

## 11. Notas de implementación

- **Sin commits intermedios**: por pedido del usuario, todo el workstream se entrega en
  un único commit final una vez validado.

## 12. Refactor prerequisito: lazy imports de torch

**Blocker descubierto y confirmado empíricamente:** el Nodo A (`python:3.11-slim`,
`edge=[]`, sin torch) no puede importar `eovrt_media.runtime.two_node`. La cadena de
imports es eager:

```
two_node.py → from eovrt_media.models import create_adapter
  → models/__init__.py importa grounding_dino_adapter y yoloe_adapter (nivel módulo)
    → grounding_dino_adapter: import torch + from transformers import ...
    → runtime_utils: import torch
```

El Nodo A solo necesita `adapter.input_spec` (target_size para normalizar) — nunca
infiere, nunca llama `load()`, no necesita torch. Los imports eager lo obligan igual.

**Solución — diferir los imports pesados a donde se usan:**

1. `models/runtime_utils.py`: mover `import torch` adentro de `resolve_device()` (única
   función que lo usa; `should_use_half` y `make_warmup_image` no lo necesitan).
2. `models/grounding_dino_adapter.py`: mover `import torch` (usado en `load`, inferencia
   y `close`) y `from transformers import ...` (usado en `load`) adentro de esos métodos.
3. `models/__init__.py`: mover los imports de `GroundingDinoHFAdapter` y
   `YOLOEUltralyticsAdapter` adentro de las ramas de `create_adapter()`; quitarlos de los
   imports a nivel módulo y de `__all__`. `MockDetectorAdapter` y `BaseDetectorAdapter`
   quedan eager (no usan torch).

**Compatibilidad:** nadie importa los adapters concretos desde el paquete
`eovrt_media.models` — los tests (`test_gdino_runtime.py`, `test_yoloe_runtime.py`) los
importan de su submódulo directo, que no cambia. Solo se consume `create_adapter`.

**Guard de regresión:** test que bloquea `torch` vía `__import__` y verifica que
`eovrt_media.runtime.two_node` y `create_adapter` (rama yoloe, sin `load()`) funcionan.
