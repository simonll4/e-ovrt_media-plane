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
eovrt-media run --config configs/dbe_grounding_dino_cr01_cr02.yaml
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
├── cli.py              # CLI con Typer
├── config.py           # Carga y validación de configuración
├── contracts.py        # Contratos Pydantic (VisualUnit, Detection, etc.)
├── sources.py          # Fuentes de datos (ImageFolderSource)
├── pipeline.py         # Orquestación del pipeline DBE
├── sinks.py            # Escritura de resultados (JSONL, JSON)
├── metrics.py          # Métricas de latencia
├── visualize.py        # Previews anotadas
└── adapters/           # Adaptadores de modelo
    ├── base.py         # Interfaz común BaseDetectorAdapter
    ├── grounding_dino_hf.py
    └── yoloe_ultralytics.py
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
