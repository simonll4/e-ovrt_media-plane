# E-OVRT-VDP Media Plane

Repositorio experimental del plano de medios de E-OVRT-VDP.

Este componente implementa la ruta crítica visual: ingesta de fuentes DBE,
normalización, transporte productor/consumidor, inferencia open-vocabulary,
postproceso y persistencia de artefactos versionados.

El camino operativo actual es **DBE en un host**. EBE, IPC y dos nodos tienen
contratos y gating explícitos, pero no backends concretos. El detalle verificable
está en [docs/implementation-status.md](docs/implementation-status.md).

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

### Ejecutar pipeline

```bash
# Con Grounding DINO
make run-gdino

# Con YOLOE
make run-yoloe

# Con CLI directamente
eovrt-media run --config configs/runs/gdino.yaml
```

`configs/runs/mock.yaml` no descarga pesos, pero requiere que la fuente del catálogo
`dataset_v1` exista en `data/samples/images/dataset_v1`.

### Ver resultados

```bash
ls runs/
cat runs/<run_id>/summary.json
head runs/<run_id>/detections.jsonl
eovrt-media inspect-run runs/<run_id>
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
├── cli.py              # CLI con Typer (run, validate-config, inspect-run, compare-runs, download-models)
├── config/             # Esquemas Pydantic + loader con resolución de refs a catálogos
├── contracts/          # Contratos Pydantic (VisualUnit, NormalizedUnit, eventos)
├── sources/            # Fuentes de datos (ImageFolderSource, VideoFileSource)
├── models/             # Adaptadores de modelo (mock, grounding_dino, yoloe)
├── preprocessing/      # Normalización de unidades visuales
├── postprocessing/     # Filtros y normalización de detecciones
├── runtime/            # Productor/consumidor, orquestación y contexto de corrida
├── transport/          # Interfaz de canal y backend memory; IPC/red declarados
├── metrics/            # Timers y agregación de métricas (p95/p99, FPS)
├── sinks/              # Persistencia de artefactos en runs/<run_id>/
└── visualize.py        # Utilidad de renderizado de detecciones

configs/                # Catálogos + run configs (ver configs/README.md)
├── models/             # Catálogo de modelos: un YAML por variante de pesos
├── datasets/           # Catálogo de fuentes de datos
├── prompts/            # Catálogo de prompt sets versionados
└── runs/               # Configs ejecutables que componen los catálogos

models/                 # Pesos por familia y linaje (ver models/README.md)
├── yoloe/{original,finetuned}/
└── grounding-dino/{original,finetuned}/
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
