# E-OVRT-VDP Media Plane

Repositorio experimental del plano de medios de E-OVRT-VDP.

Este componente implementa la ruta crítica visual: ingesta de fuentes DBE/EBE,
normalización, transporte productor/consumidor, inferencia open-vocabulary,
postproceso y persistencia de artefactos versionados.

Las cuatro combinaciones escenario × topología están implementadas: DBE/EBE en
un host y en dos nodos (ZeroMQ). El detalle verificable está en
[docs/implementation-status.md](docs/implementation-status.md).

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
# Smoke test sin pesos (mock detector, CHV demo v2)
make run-mock

# Con Grounding DINO tiny (requiere modelos descargados)
make run-gdino

# Con YOLOE-26s (requiere modelos descargados)
make run-yoloe

# Con CLI directamente
eovrt-media run --config configs/runs/gdino.yaml

# Topología dos nodos (Nodo A ingesta, Nodo B inferencia)
eovrt-media run-producer --config configs/runs/<archivo>.yaml
eovrt-media run-consumer --config configs/runs/<archivo>.yaml
```

Los sample runs (`mock`, `gdino`, `yoloe`) apuntan al dataset CHV demo v2 del
repo hermano `../e-ovrt_datasets`. El smoke test mock valida el pipeline completo
sin necesitar pesos de modelos.

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
├── sources/            # Fuentes de datos (ImageFolderSource, VideoFileSource, RtspSource, OakDSource)
├── models/             # Adaptadores de modelo (mock, grounding_dino, yoloe)
├── preprocessing/      # Normalización de unidades visuales
├── postprocessing/     # Filtros y normalización de detecciones
├── runtime/            # Productor/consumidor, orquestación, two-node
├── transport/          # Canal productor/consumidor (memory y network/ZeroMQ)
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
