# E-OVRT-VDP Media Plane

Repositorio experimental del plano de medios de E-OVRT-VDP.

Este componente implementa la ruta crítica visual: lectura de fuentes DBE,
normalización de unidades visuales, inferencia open-vocabulary mediante adaptadores
de modelo, postproceso, persistencia de detecciones y métricas básicas.

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

### Ver resultados

```bash
ls runs/
cat runs/<run_id>/summary.json
head runs/<run_id>/detections.jsonl
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
├── contracts/          # Contratos Pydantic (VisualUnit, Detection, eventos)
├── sources/            # Fuentes de datos (ImageFolderSource, VideoFileSource)
├── models/             # Adaptadores de modelo (mock, grounding_dino, yoloe)
├── preprocessing/      # Normalización de unidades visuales
├── postprocessing/     # Filtros y normalización de detecciones
├── runtime/            # Orquestación del pipeline y contexto de corrida
├── metrics/            # Timers y agregación de métricas (p95/p99, FPS)
├── sinks/              # Persistencia de artefactos en runs/<run_id>/
└── visualize.py        # Previews anotadas

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
