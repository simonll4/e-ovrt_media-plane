# E-OVRT-VDP Media Plane

Repositorio experimental del plano de medios de E-OVRT-VDP.

Este componente implementa la ruta crítica visual: ingesta de fuentes DBE/EBE,
normalización, transporte productor/consumidor, inferencia open-vocabulary,
postproceso y persistencia de artefactos versionados.

Desde la **Fase 1 (Spec A)** el media-plane **no es un CLI**: es un **servicio de
inferencia HTTP/WS** (FastAPI) que carga el modelo una vez al startup y mantiene un
único run activo. Las corridas se disparan por `POST /api/runs`; los utilitarios
ex-subcomandos se invocan como módulos (`python -m eovrt_media.tools.*`). La guía
completa de uso está en [docs/usage.md](docs/usage.md).

Las cuatro combinaciones escenario × topología están implementadas: DBE/EBE en un host
(`memory`) y en dos nodos (`network`/ZeroMQ, hoy invocado en proceso). El detalle
verificable está en [docs/implementation-status.md](docs/implementation-status.md).

**No implementa** patrones de riesgo, alertas, UI, notificaciones, MOT formal, zonas ni lógica de plano de control.

---

## Quick Start

### Instalación

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip setuptools wheel
pip install -e ".[dev]"
```

### Descarga de modelos

```bash
make download-models
```

### Levantar el servicio

El **modelo se carga una vez al startup** desde `EOVRT_MODEL_REF` (una `ref` del
catálogo `configs/models/`, o `mock` para validar sin pesos). Correr **desde la raíz**
del media-plane (los catálogos de datasets usan rutas `../e-ovrt_datasets` relativas al CWD).

```bash
# uvicorn --factory eovrt_media.service.app:create_app en :8080
EOVRT_MODEL_REF=mock make serve

# Smoke: verifica /healthz + /readyz
make smoke
```

### Disparar una corrida

El modelo nunca viaja en el request (es fijo por instancia); el body declara la fuente
de ingesta y los prompts. Un solo run activo a la vez (un segundo POST → 409).

```bash
curl -X POST http://localhost:8080/api/runs \
  -H "Content-Type: application/json" \
  -d '{
        "ingest": {"plugin": "image_folder", "config": {"path": "/ruta/a/imagenes"}},
        "prompts": {
          "set_inline": {
            "id": "demo",
            "classes": [{"id": "person", "phrasings": {"default": ["person"]}}]
          },
          "active_ids": ["person"]
        }
      }'
# -> 201 {"run_id": "run_..."}
```

Para usar un dataset del catálogo, pasar `config.dataset: <nombre>` en vez de `path`.
Ver [docs/usage.md](docs/usage.md) para el contrato completo (WebSocket de eventos,
artefactos por HTTP, detener/borrar corridas) y la topología dos nodos.

### Ver resultados

```bash
ls runs/
cat runs/<run_id>/summary.json
head runs/<run_id>/detections.jsonl
python -m eovrt_media.tools.inspect_runs inspect runs/<run_id>
```

### Linting y tests

```bash
make lint
make test
```

---

## Estructura

```
src/eovrt_media/        # Paquete principal
├── service/            # Servicio FastAPI: app+lifespan, settings, RunManager, events, routers/
├── tools/              # Utilitarios ex-CLI (evaluate, inspect_runs, debug_run) — python -m
├── config/             # Esquemas Pydantic + loader (dict-based, resolve_model_ref, set_inline)
├── contracts/          # Contratos Pydantic (VisualUnit, NormalizedUnit, eventos)
├── sources/            # Fuentes + registry de plugins de ingesta (image_folder, video_file, rtsp, oak_d)
├── models/             # Adaptadores de modelo (mock, grounding_dino, yoloe)
├── preprocessing/      # Normalización de unidades visuales
├── postprocessing/     # Filtros y normalización de detecciones
├── runtime/            # Productor/consumidor, execute_run + RunControl, two-node
├── transport/          # Canal productor/consumidor (memory y network/ZeroMQ)
├── metrics/            # Timers y agregación de métricas (p95/p99, FPS)
├── sinks/              # Persistencia de artefactos en runs/<run_id>/
└── visualize.py        # Utilidad de renderizado de detecciones
```

> **Caveat `debug_run`:** la ruta de dos-nodos-local de `python -m eovrt_media.tools.debug_run`
> (`run_two_node_local`) no funciona tras la eliminación del CLI — spawnea el
> `eovrt_media.cli` borrado y falla con un `RuntimeError` explícito. Su reemplazo es el
> split two-node dockerizado de `infra/twonode/` (Fase 2, ya completada y verificada); el
> banco de debug local queda permanentemente deshabilitado y no tiene puente hacia ese
> despliegue Docker. `evaluate` e `inspect_runs` no están afectados.

```
configs/                # Catálogos de capacidades (ver configs/README.md)
├── models/             # Catálogo de modelos: un YAML por variante de pesos
└── datasets/           # Catálogo de fuentes de datos
#   (los manifiestos de corrida viven en el repo hermano e-ovrt_experimental-setup;
#    el servicio recibe el request por POST /api/runs)

models/                 # Pesos por familia y linaje (ver models/README.md)
├── yoloe/{original,finetuned}/
├── grounding-dino/{original,finetuned}/
└── mm-grounding-dino/{original,finetuned}/
```

---

## Adaptadores soportados

| Modelo          | Adaptador                | Backend       |
|-----------------|--------------------------|---------------|
| Grounding DINO  | `grounding_dino_hf`      | Transformers  |
| YOLOE           | `yoloe_ultralytics`      | Ultralytics   |
| Mock (testing)  | `mock`                   | —             |

---

## Licencia

Uso interno — E-OVRT-VDP.
