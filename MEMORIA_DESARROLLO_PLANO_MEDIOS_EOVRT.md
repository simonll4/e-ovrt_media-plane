# Memoria de desarrollo — Plano de Medios E-OVRT-VDP

> Archivo de contexto para trabajar con Codex en VS Code.  
> Este documento debe tratarse como la **memoria técnica base** del repositorio del **plano de medios**.  
> El repositorio del plano de medios es un módulo independiente que más adelante se integrará con el resto de la plataforma E-OVRT-VDP.

---

## 1. Contexto general del proyecto

El proyecto E-OVRT-VDP corresponde al TFG/tesis:

**“Plataforma experimental de detección open-vocabulary en video en tiempo real para monitoreo asistivo de riesgos en construcción”.**

El sistema completo se concibe como una plataforma experimental que procesa video o fuentes visuales, ejecuta detección open-vocabulary, produce evidencia perceptiva normalizada, evalúa patrones de riesgo y registra alertas asistivas trazables.

El proyecto **no** es un producto industrial terminado, **no** es una herramienta de fiscalización automática, **no** sustituye al supervisor humano y **no** realiza reconocimiento de identidad personal.

El desarrollo actual parte de la **Etapa 3 cerrada**, donde quedó definido el diseño arquitectónico. La implementación debe avanzar de forma incremental, comenzando por el núcleo validable más simple:

- escenario **DBE**: Dataset-Based Evaluation;
- condiciones núcleo **CR-01** y **CR-02**;
- detección OVD frame-a-frame;
- evidencia perceptiva normalizada;
- métricas técnicas por corrida;
- trazabilidad experimental.

---

## 2. Qué es el plano de medios

El **plano de medios** es la ruta crítica de procesamiento visual.

Su responsabilidad es transformar una fuente visual en evidencia perceptiva normalizada y medible.

En términos simples:

```text
fuente visual -> unidad visual -> preprocesamiento -> modelo OVD -> postproceso -> DetectionEvent + MetricSample
```

El plano de medios recibe imágenes, frames o video. Luego controla el ritmo de procesamiento, normaliza la entrada, ejecuta inferencia open-vocabulary, normaliza detecciones, mide tiempos y escribe eventos de salida.

El producto final del plano de medios **no es una alerta**.  
El producto final es **evidencia visual primaria, normalizada y trazable**.

---

## 3. Frontera arquitectónica

Este repositorio implementa **solo** el plano de medios.

El plano de medios debe producir evidencia como:

```text
“En el frame 120 detecté persona, casco, chaleco o maquinaria,
con estas cajas, scores, timestamps, modelo, prompts, configuración y métricas.”
```

El plano de control, que irá en otro módulo/repositorio, decidirá cosas como:

```text
“La persona estuvo sin casco durante 4 segundos,
entonces se confirma PR-01 y se registra una alerta interna.”
```

### 3.1 Incluido en este repositorio

Este repo debe incluir:

- carga de configuración de corrida;
- lectura de fuentes DBE;
- lectura de imágenes desde carpeta;
- lectura de video local;
- muestreo simple de frames;
- normalización de unidades visuales;
- adaptadores de modelos OVD;
- integración inicial con **Grounding DINO**;
- integración inicial con **YOLOE**;
- modelo `mock` para pruebas rápidas;
- postproceso mínimo de detecciones;
- normalización de bounding boxes;
- escritura de eventos JSONL;
- escritura de métricas JSONL;
- escritura de errores JSONL;
- generación de `summary.json`;
- estructura de directorios clara;
- CLI mínima para ejecutar corridas.

### 3.2 Fuera de alcance por ahora

No implementar todavía:

- evaluación de patrones de riesgo;
- severidad;
- persistencia temporal de patrones;
- confirmación de alertas;
- notificaciones;
- UI;
- dashboards;
- base de datos;
- streaming RTSP/WebRTC/SRT;
- MediaMTX;
- Edge Node;
- Training Node;
- MOT formal;
- zonas espaciales;
- reglas relacionales complejas;
- fine-tuning;
- TensorRT/ONNX como dependencia base;
- microservicios;
- Kafka, MQTT, NATS, Redis o colas externas.

Todo eso puede existir después, pero no pertenece al primer núcleo del plano de medios.

---

## 4. Objetivo inmediato del repositorio

Construir un pipeline mínimo para comparar modelos OVD sobre fuentes locales.

Objetivo del primer entregable:

```text
Dado un RunConfig, leer imágenes o video local,
ejecutar Grounding DINO o YOLOE con prompts CR-01/CR-02,
normalizar detecciones y guardar eventos + métricas por corrida.
```

La implementación inicial debe permitir correr:

```bash
eovrt-media run --config configs/dbe_cr01_cr02_grounding_dino.yaml
eovrt-media run --config configs/dbe_cr01_cr02_yoloe.yaml
eovrt-media run --config configs/dbe_cr01_cr02_mock.yaml
```

---

## 5. Condiciones núcleo del TFG

El núcleo validable inicial se enfoca en dos condiciones:

### CR-01 — Persona sin casco

Descripción conceptual:

```text
Persona sin casco de seguridad en zona de obra.
```

Para el plano de medios, esto **no** debe implementarse como “sin casco” todavía.  
El plano de medios debe detectar entidades base:

- `person`
- `helmet`
- `safety helmet`
- variantes equivalentes según el modelo

La interpretación “persona sin casco” pertenece al plano de control.

### CR-02 — Persona sin chaleco reflectivo

Descripción conceptual:

```text
Persona sin chaleco reflectivo en zona de tráfico/maquinaria.
```

Para el plano de medios, esto se traduce en detecciones base:

- `person`
- `safety vest`
- `reflective vest`
- `high visibility vest`
- eventualmente `vehicle`, `truck`, `machine`, `excavator` como entidades auxiliares futuras

La interpretación “persona sin chaleco” pertenece al plano de control.

---

## 6. Prompts iniciales

Usar prompts simples y versionados.

Archivo sugerido:

```text
configs/prompts/cr01_cr02_v1.yaml
```

Contenido sugerido:

```yaml
prompt_set:
  id: cr01_cr02_v1
  description: "Prompts iniciales para detección perceptiva de CR-01 y CR-02"
  language: en
  items:
    - id: person
      text: "person"
      role: entity

    - id: helmet
      text: "safety helmet"
      role: ppe

    - id: vest
      text: "high visibility safety vest"
      role: ppe

    - id: reflective_vest
      text: "reflective vest"
      role: ppe

    - id: construction_vehicle
      text: "construction vehicle"
      role: context
      enabled_by_default: false
```

Notas:

- Grounding DINO suele usar prompts concatenados separados por punto:
  ```text
  person. safety helmet. high visibility safety vest. reflective vest.
  ```
- YOLOE permite configurar clases con `set_classes([...])`.
- Mantener todos los prompts en configuración; no hardcodear prompts en código.

---

## 7. Modelos iniciales

El repo debe soportar tres adaptadores iniciales:

1. `mock`
2. `grounding_dino`
3. `yoloe`

### 7.1 MockDetector

Sirve para validar el pipeline sin depender de CUDA ni descargas.

Debe devolver detecciones falsas pero estructuralmente válidas.

Uso:

```bash
eovrt-media run --config configs/dbe_cr01_cr02_mock.yaml
```

Objetivo:

- probar lectura de imágenes;
- probar escritura JSONL;
- probar métricas;
- probar estructura de outputs;
- probar CLI;
- probar tests unitarios.

### 7.2 Grounding DINO

Integración recomendada al inicio: Hugging Face Transformers.

Dependencias principales:

```bash
pip install torch torchvision transformers pillow opencv-python pydantic pyyaml typer rich
```

Ejemplo conceptual:

```python
import torch
from PIL import Image
from transformers import AutoProcessor, AutoModelForZeroShotObjectDetection

model_id = "IDEA-Research/grounding-dino-tiny"

processor = AutoProcessor.from_pretrained(model_id)
model = AutoModelForZeroShotObjectDetection.from_pretrained(model_id).to(device)

text = "person. safety helmet. high visibility safety vest."
image = Image.open(path).convert("RGB")

inputs = processor(images=image, text=text, return_tensors="pt").to(device)

with torch.no_grad():
    outputs = model(**inputs)

results = processor.post_process_grounded_object_detection(
    outputs,
    inputs.input_ids,
    box_threshold=0.30,
    text_threshold=0.25,
    target_sizes=[image.size[::-1]],
)
```

Modelo recomendado para primera prueba:

```text
IDEA-Research/grounding-dino-tiny
```

Luego comparar con:

```text
IDEA-Research/grounding-dino-base
```

Notas de diseño:

- El adaptador debe esconder todo lo específico de Hugging Face.
- El pipeline no debe depender de objetos `processor` ni `outputs` de Transformers.
- El adaptador debe devolver una lista interna de `RawDetection`.
- La normalización final la hace `detection_normalizer.py`.
- No asumir que las etiquetas del modelo coinciden exactamente con los `prompt_id`.
- Conservar `prompt_text`, `prompt_id`, `model_name`, `model_id` y umbrales usados.

### 7.3 YOLOE

Integración recomendada al inicio: Ultralytics.

Instalación:

```bash
pip install -U ultralytics
```

Ejemplo conceptual:

```python
from ultralytics import YOLOE

model = YOLOE("yoloe-26s-seg.pt")
model.set_classes(["person", "safety helmet", "high visibility safety vest"])

results = model.predict("path/to/image.jpg", conf=0.25)
```

Notas:

- Usar modelo chico primero:
  ```text
  yoloe-26s-seg.pt
  ```
- Si ese checkpoint no está disponible en el entorno, permitir configurar otro:
  ```text
  yoloe-26l-seg.pt
  yoloe-11s-seg.pt
  yoloe-v8s-seg.pt
  ```
- No acoplar el pipeline a segmentación. Aunque YOLOE pueda devolver máscaras, para el núcleo inicial usar solo boxes.
- `set_classes()` debe ejecutarse una vez por carga de modelo con los prompts activos.
- El adaptador debe convertir resultados Ultralytics a `RawDetection`.
- Mantener YOLOE como adaptador reemplazable.

---

## 8. Estructura simple del repositorio

Nombre sugerido del repo:

```text
eovrt-media-plane
```

Estructura inicial:

```text
eovrt-media-plane/
│
├── README.md
├── pyproject.toml
├── .gitignore
├── .env.example
├── Makefile
│
├── configs/
│   ├── dbe_cr01_cr02_mock.yaml
│   ├── dbe_cr01_cr02_grounding_dino.yaml
│   ├── dbe_cr01_cr02_yoloe.yaml
│   └── prompts/
│       └── cr01_cr02_v1.yaml
│
├── data/
│   ├── samples/
│   │   └── README.md
│   └── README.md
│
├── runs/
│   └── .gitkeep
│
├── models/
│   └── README.md
│
├── docs/
│   ├── MEMORY_MEDIA_PLANE.md
│   ├── architecture.md
│   ├── contracts.md
│   ├── metrics.md
│   └── decisions/
│       ├── ADR-0001-media-plane-scope.md
│       ├── ADR-0002-dbe-first.md
│       ├── ADR-0003-model-adapters.md
│       └── ADR-0004-jsonl-run-artifacts.md
│
├── scripts/
│   ├── download_models.py
│   ├── run_sample_mock.sh
│   ├── run_sample_grounding_dino.sh
│   └── run_sample_yoloe.sh
│
├── src/
│   └── eovrt_media/
│       ├── __init__.py
│       ├── cli.py
│       ├── app.py
│       │
│       ├── config/
│       │   ├── __init__.py
│       │   ├── loader.py
│       │   └── schemas.py
│       │
│       ├── contracts/
│       │   ├── __init__.py
│       │   ├── visual_unit.py
│       │   ├── detection.py
│       │   ├── events.py
│       │   ├── metrics.py
│       │   └── errors.py
│       │
│       ├── sources/
│       │   ├── __init__.py
│       │   ├── base.py
│       │   ├── image_folder_source.py
│       │   └── video_file_source.py
│       │
│       ├── preprocessing/
│       │   ├── __init__.py
│       │   └── image_loader.py
│       │
│       ├── models/
│       │   ├── __init__.py
│       │   ├── base.py
│       │   ├── mock_detector.py
│       │   ├── grounding_dino_adapter.py
│       │   └── yoloe_adapter.py
│       │
│       ├── postprocessing/
│       │   ├── __init__.py
│       │   └── detection_normalizer.py
│       │
│       ├── sinks/
│       │   ├── __init__.py
│       │   ├── jsonl_sink.py
│       │   └── run_artifact_writer.py
│       │
│       ├── metrics/
│       │   ├── __init__.py
│       │   ├── timers.py
│       │   └── collector.py
│       │
│       └── runtime/
│           ├── __init__.py
│           ├── pipeline.py
│           └── run_context.py
│
└── tests/
    ├── test_config_loader.py
    ├── test_image_folder_source.py
    ├── test_detection_normalizer.py
    ├── test_jsonl_sink.py
    └── test_pipeline_mock.py
```

Mantener esta estructura simple. No agregar carpetas innecesarias todavía.

---

## 9. Artefactos de salida por corrida

Cada corrida debe generar una carpeta en `runs/`.

Ejemplo:

```text
runs/
└── run_20260609_013045_grounding_dino/
    ├── run_config.yaml
    ├── effective_config.yaml
    ├── run_manifest.json
    ├── detections.jsonl
    ├── metrics.jsonl
    ├── errors.jsonl
    ├── summary.json
    └── previews/
        └── frame_000001.jpg
```

### 9.1 `effective_config.yaml`

Debe guardar la configuración realmente usada.  
No alcanza con conservar el archivo original porque puede haber defaults resueltos en runtime.

### 9.2 `detections.jsonl`

Un evento por unidad visual procesada.

Cada línea JSON debe ser independiente y parseable.

### 9.3 `metrics.jsonl`

Una muestra métrica por unidad visual o por tramo relevante.

### 9.4 `errors.jsonl`

Errores recuperables, warnings importantes y unidades fallidas.

### 9.5 `summary.json`

Resumen final de la corrida.

Debe incluir mínimo:

- `run_id`;
- fecha/hora de inicio;
- fecha/hora de fin;
- duración;
- escenario;
- tipo de fuente;
- modelo;
- prompts;
- frames/imágenes procesadas;
- errores;
- FPS efectivo;
- latencia promedio;
- latencia p95;
- cantidad total de detecciones;
- dispositivo usado;
- versión del esquema.

---

## 10. Contratos internos

Los contratos son más importantes que el modelo.  
El modelo debe ser reemplazable sin cambiar el resto del pipeline.

### 10.1 RunConfig

Representa la configuración declarativa de la corrida.

Ejemplo:

```yaml
run:
  id: null
  scenario: DBE
  description: "Prueba mínima CR-01/CR-02 con Grounding DINO"
  seed: 42

source:
  type: image_folder
  path: data/samples/images
  extensions: [".jpg", ".jpeg", ".png"]

sampling:
  mode: all
  every_n: 1
  target_fps: null
  max_units: null

model:
  name: grounding_dino
  model_id: IDEA-Research/grounding-dino-tiny
  device: cuda
  confidence_threshold: 0.30
  box_threshold: 0.30
  text_threshold: 0.25

prompts:
  file: configs/prompts/cr01_cr02_v1.yaml

postprocess:
  min_confidence: 0.25
  min_box_area_px: 100
  normalize_boxes: true

outputs:
  run_dir: runs
  save_detections_jsonl: true
  save_metrics_jsonl: true
  save_errors_jsonl: true
  save_previews: false
  preview_max: 20

logging:
  level: INFO
```

### 10.2 VisualUnit

Representa una imagen o frame procesable.

```json
{
  "run_id": "run_20260609_013045_grounding_dino",
  "unit_id": "unit_000001",
  "source_id": "ppe_sample_001.jpg",
  "source_type": "image_folder",
  "frame_index": null,
  "timestamp_ms": null,
  "width": 1280,
  "height": 720,
  "path": "data/samples/images/ppe_sample_001.jpg"
}
```

### 10.3 RawDetection

Salida intermedia de un adaptador de modelo.

```json
{
  "label": "safety helmet",
  "score": 0.78,
  "bbox_xyxy": [120.0, 45.0, 210.0, 135.0],
  "source_prompt": "safety helmet",
  "prompt_id": "helmet",
  "raw": {}
}
```

No persistir `raw` completo por defecto si es grande.  
Debe ser opcional y activable por config.

### 10.4 DetectionEvent

Evento persistible producido por el plano de medios.

```json
{
  "schema_version": "media.detection.v1",
  "event_type": "detection_event",
  "run_id": "run_20260609_013045_grounding_dino",
  "unit_id": "unit_000001",
  "source": {
    "source_id": "ppe_sample_001.jpg",
    "source_type": "image_folder",
    "frame_index": null,
    "timestamp_ms": null,
    "width": 1280,
    "height": 720
  },
  "model": {
    "name": "grounding_dino",
    "model_id": "IDEA-Research/grounding-dino-tiny",
    "device": "cuda"
  },
  "prompts": {
    "prompt_set_id": "cr01_cr02_v1"
  },
  "detections": [
    {
      "detection_id": "det_000001",
      "label": "person",
      "prompt_id": "person",
      "confidence": 0.86,
      "bbox_xyxy": [100.0, 70.0, 400.0, 700.0],
      "bbox_norm_xyxy": [0.0781, 0.0972, 0.3125, 0.9722],
      "area_px": 189000.0
    }
  ],
  "timing": {
    "read_ms": 2.1,
    "preprocess_ms": 4.3,
    "inference_ms": 87.4,
    "postprocess_ms": 2.6,
    "write_ms": 0.8,
    "total_ms": 97.2
  }
}
```

### 10.5 MetricSample

```json
{
  "schema_version": "media.metric.v1",
  "event_type": "metric_sample",
  "run_id": "run_20260609_013045_grounding_dino",
  "unit_id": "unit_000001",
  "fps_effective": 8.4,
  "latency_total_ms": 97.2,
  "latency_inference_ms": 87.4,
  "detections_count": 3,
  "dropped_units": 0,
  "device": "cuda",
  "gpu_memory_allocated_mb": 3120.5
}
```

### 10.6 ErrorEvent

```json
{
  "schema_version": "media.error.v1",
  "event_type": "error_event",
  "run_id": "run_20260609_013045_grounding_dino",
  "unit_id": "unit_000023",
  "stage": "inference",
  "severity": "error",
  "message": "CUDA out of memory",
  "recoverable": true
}
```

---

## 11. CLI mínima

Usar `Typer` para una CLI simple.

Comandos deseados:

```bash
eovrt-media run --config configs/dbe_cr01_cr02_mock.yaml
eovrt-media inspect-run runs/run_...
eovrt-media validate-config configs/dbe_cr01_cr02_grounding_dino.yaml
eovrt-media download-models --model grounding_dino
eovrt-media download-models --model yoloe
```

Prioridad:

1. `run`
2. `validate-config`
3. `download-models`
4. `inspect-run`

---

## 12. Pipeline mínimo

El pipeline debe implementarse de forma lineal y clara.

Pseudocódigo:

```python
def run_pipeline(config_path: Path) -> None:
    config = load_config(config_path)
    run_context = create_run_context(config)
    artifact_writer = RunArtifactWriter(run_context)

    artifact_writer.write_original_config(config_path)
    artifact_writer.write_effective_config(config)

    source = create_source(config.source)
    model = create_model_adapter(config.model)
    prompts = load_prompts(config.prompts.file)

    model.load(prompts)

    for visual_unit in source.iter_units():
        with timers.measure_unit() as timing:
            image = load_image(visual_unit)
            raw_detections = model.infer(image=image, visual_unit=visual_unit, prompts=prompts)
            detections = normalize_detections(raw_detections, visual_unit, config.postprocess)

        detection_event = build_detection_event(...)
        metric_sample = build_metric_sample(...)

        artifact_writer.write_detection(detection_event)
        artifact_writer.write_metric(metric_sample)

    model.unload()
    artifact_writer.write_summary()
```

Reglas:

- No meter lógica de CR-01/CR-02 en el pipeline.
- No detectar “sin casco” como estado.
- No generar alertas.
- No bloquear escritura de eventos por previews.
- No romper ejecución completa por una imagen fallida: registrar error y continuar si es recuperable.
- Separar `RawDetection` de `DetectionEvent`.
- Separar adaptador de modelo de normalización.
- Mantener el pipeline fácil de leer.

---

## 13. Configs iniciales

### 13.1 Mock

```yaml
run:
  id: null
  scenario: DBE
  description: "Smoke test con MockDetector"
  seed: 42

source:
  type: image_folder
  path: data/samples/images
  extensions: [".jpg", ".jpeg", ".png"]

sampling:
  mode: all
  every_n: 1
  target_fps: null
  max_units: 10

model:
  name: mock
  model_id: mock-v1
  device: cpu
  confidence_threshold: 0.25

prompts:
  file: configs/prompts/cr01_cr02_v1.yaml

postprocess:
  min_confidence: 0.25
  min_box_area_px: 100
  normalize_boxes: true

outputs:
  run_dir: runs
  save_previews: false
```

### 13.2 Grounding DINO

```yaml
run:
  id: null
  scenario: DBE
  description: "Prueba mínima CR-01/CR-02 con Grounding DINO"
  seed: 42

source:
  type: image_folder
  path: data/samples/images
  extensions: [".jpg", ".jpeg", ".png"]

sampling:
  mode: all
  every_n: 1
  target_fps: null
  max_units: 25

model:
  name: grounding_dino
  model_id: IDEA-Research/grounding-dino-tiny
  device: cuda
  confidence_threshold: 0.30
  box_threshold: 0.30
  text_threshold: 0.25

prompts:
  file: configs/prompts/cr01_cr02_v1.yaml

postprocess:
  min_confidence: 0.25
  min_box_area_px: 100
  normalize_boxes: true

outputs:
  run_dir: runs
  save_previews: true
  preview_max: 10
```

### 13.3 YOLOE

```yaml
run:
  id: null
  scenario: DBE
  description: "Prueba mínima CR-01/CR-02 con YOLOE"
  seed: 42

source:
  type: image_folder
  path: data/samples/images
  extensions: [".jpg", ".jpeg", ".png"]

sampling:
  mode: all
  every_n: 1
  target_fps: null
  max_units: 25

model:
  name: yoloe
  model_id: yoloe-26s-seg.pt
  device: cuda
  confidence_threshold: 0.25
  image_size: 640

prompts:
  file: configs/prompts/cr01_cr02_v1.yaml

postprocess:
  min_confidence: 0.25
  min_box_area_px: 100
  normalize_boxes: true

outputs:
  run_dir: runs
  save_previews: true
  preview_max: 10
```

---

## 14. pyproject.toml sugerido

```toml
[project]
name = "eovrt-media-plane"
version = "0.1.0"
description = "Plano de medios experimental para E-OVRT-VDP"
readme = "README.md"
requires-python = ">=3.11"
dependencies = [
    "pydantic>=2.0",
    "pyyaml>=6.0",
    "typer>=0.12",
    "rich>=13.0",
    "pillow>=10.0",
    "opencv-python>=4.9",
    "numpy>=1.26",
    "torch",
    "torchvision",
    "transformers",
    "ultralytics",
]

[project.scripts]
eovrt-media = "eovrt_media.cli:app"

[tool.ruff]
line-length = 100

[tool.pytest.ini_options]
testpaths = ["tests"]
markers = [
    "slow: integration tests that may require model downloads or GPU",
    "gpu: tests that require CUDA",
]
```

---

## 15. .gitignore sugerido

```gitignore
.venv/
__pycache__/
*.pyc
.pytest_cache/
.ruff_cache/

runs/*
!runs/.gitkeep

data/raw/
data/datasets/
data/videos/
data/samples/images/*
!data/samples/README.md

models/*.pt
models/*.pth
models/*.onnx
models/*.engine

.env
.DS_Store
```

---

## 16. Makefile sugerido

```makefile
.PHONY: install test lint run-mock run-gdino run-yoloe

install:
	pip install -e .

test:
	pytest

lint:
	ruff check src tests

run-mock:
	eovrt-media run --config configs/dbe_cr01_cr02_mock.yaml

run-gdino:
	eovrt-media run --config configs/dbe_cr01_cr02_grounding_dino.yaml

run-yoloe:
	eovrt-media run --config configs/dbe_cr01_cr02_yoloe.yaml
```

---

## 17. Script de descarga de modelos

Archivo:

```text
scripts/download_models.py
```

Objetivo:

- forzar descarga/caché de Grounding DINO;
- verificar que Ultralytics pueda cargar YOLOE;
- no bloquear el pipeline si un modelo no está instalado;
- imprimir instrucciones claras.

Pseudocódigo:

```python
def download_grounding_dino(model_id: str):
    from transformers import AutoProcessor, AutoModelForZeroShotObjectDetection
    AutoProcessor.from_pretrained(model_id)
    AutoModelForZeroShotObjectDetection.from_pretrained(model_id)

def download_yoloe(model_id: str):
    from ultralytics import YOLOE
    YOLOE(model_id)

if __name__ == "__main__":
    download_grounding_dino("IDEA-Research/grounding-dino-tiny")
    download_yoloe("yoloe-26s-seg.pt")
```

Notas:

- Hugging Face descarga en caché automáticamente.
- Ultralytics puede descargar o buscar el `.pt` según versión/modelo.
- Si YOLOE no resuelve el checkpoint automáticamente, descargar manualmente el `.pt` y ubicarlo en `models/`, luego configurar:
  ```yaml
  model_id: models/yoloe-26s-seg.pt
  ```

---

## 18. Tests mínimos

Implementar primero tests que no requieran modelos reales.

### Tests unitarios

```text
test_config_loader.py
test_image_folder_source.py
test_detection_normalizer.py
test_jsonl_sink.py
test_pipeline_mock.py
```

### Qué validar

- la config se carga correctamente;
- la config inválida falla con mensaje útil;
- `ImageFolderSource` lista imágenes ordenadas;
- `VisualUnit` conserva dimensiones y metadatos;
- `bbox_xyxy` se normaliza bien;
- detecciones con baja confianza se filtran;
- `detections.jsonl` tiene una línea JSON válida por unidad visual;
- `metrics.jsonl` se genera;
- `summary.json` se genera;
- el pipeline mock corre de punta a punta.

### Tests de integración posteriores

```bash
pytest -m slow
pytest -m gpu
```

Para Grounding DINO y YOLOE reales.

---

## 19. Métricas mínimas

Desde el primer día medir:

- cantidad de unidades visuales procesadas;
- cantidad de unidades fallidas;
- cantidad de detecciones;
- latencia de lectura;
- latencia de preprocesamiento;
- latencia de inferencia;
- latencia de postproceso;
- latencia de escritura;
- latencia total por unidad;
- FPS efectivo;
- VRAM asignada si `torch.cuda.is_available()`;
- errores recuperables;
- descartes por postproceso.

No hace falta calcular AP, precision, recall ni métricas de riesgo todavía.  
Eso requiere ground truth y/o plano de control.

---

## 20. Decisiones de arquitectura que deben respetarse

### DA-01 — Separación de plano de medios y plano de control

El plano de medios no decide riesgo, severidad ni alerta.

### DA-02 — Evidencia perceptiva normalizada

La salida debe tener suficiente contexto:

- run;
- fuente;
- frame;
- timestamp;
- modelo;
- prompts;
- umbrales;
- detecciones;
- latencias.

### DA-03 — Modelos por adaptadores

Grounding DINO y YOLOE son reemplazables.  
El pipeline no debe importar directamente Transformers ni Ultralytics fuera de los adaptadores.

### DA-04 — DBE primero

La primera versión trabaja con datasets, imágenes y videos locales.  
Streaming queda para después.

### DA-05 — Configuración de corrida como artefacto central

Todo lo importante debe venir de YAML.

### DA-06 — No sobre-ingeniería

No introducir infraestructura distribuida hasta que el pipeline local sea medible y estable.

---

## 21. Reglas para Codex

Cuando Codex implemente este repo, debe seguir estas reglas:

1. Mantener el repo simple.
2. No agregar servicios externos.
3. No agregar Docker hasta que se pida explícitamente.
4. No implementar plano de control.
5. No implementar alertas.
6. No implementar patrones.
7. No hardcodear prompts.
8. No hardcodear rutas absolutas.
9. No mezclar lógica de modelo con lógica de pipeline.
10. No escribir salidas fuera de `runs/`.
11. No versionar pesos de modelos.
12. No versionar datasets pesados.
13. Usar `pydantic` para configs y contratos.
14. Usar JSONL para eventos.
15. Priorizar código legible sobre optimizaciones prematuras.
16. Soportar CPU como fallback, aunque lento.
17. Usar GPU si está disponible y configurado.
18. Registrar errores y continuar cuando sea razonable.
19. Implementar primero `MockDetector`.
20. Integrar modelos reales solo después de que el pipeline mock funcione.

---

## 22. Orden de implementación recomendado

### Hito 1 — Bootstrap del repo

Crear:

- `pyproject.toml`;
- `.gitignore`;
- `README.md`;
- estructura de carpetas;
- configs iniciales;
- CLI básica;
- tests vacíos o mínimos.

Criterio de aceptación:

```bash
pip install -e .
eovrt-media --help
pytest
```

### Hito 2 — Pipeline mock

Implementar:

- `RunConfig`;
- `PromptConfig`;
- `ImageFolderSource`;
- `VisualUnit`;
- `MockDetector`;
- `DetectionNormalizer`;
- `JsonlSink`;
- `RunArtifactWriter`;
- `Pipeline`.

Criterio de aceptación:

```bash
make run-mock
```

Debe crear:

```text
runs/<run_id>/effective_config.yaml
runs/<run_id>/detections.jsonl
runs/<run_id>/metrics.jsonl
runs/<run_id>/summary.json
```

### Hito 3 — Grounding DINO

Implementar:

- `GroundingDinoAdapter`;
- carga por `model_id`;
- construcción del prompt concatenado;
- inferencia sobre imagen;
- conversión a `RawDetection`.

Criterio de aceptación:

```bash
make run-gdino
```

### Hito 4 — YOLOE

Implementar:

- `YoloeAdapter`;
- `set_classes()` desde prompt config;
- inferencia sobre imagen;
- conversión de boxes a `RawDetection`.

Criterio de aceptación:

```bash
make run-yoloe
```

### Hito 5 — Video local

Implementar:

- `VideoFileSource`;
- `frame_index`;
- `timestamp_ms`;
- `every_n`;
- `target_fps`;
- límite `max_units`.

No hacer streaming todavía.

### Hito 6 — Comparación mínima

Agregar script de inspección:

```bash
eovrt-media inspect-run runs/<run_id>
```

Debe mostrar:

- modelo;
- cantidad de unidades procesadas;
- cantidad de detecciones;
- FPS promedio;
- latencia promedio;
- latencia p95;
- errores.

---

## 23. README inicial sugerido

```markdown
# E-OVRT-VDP Media Plane

Repositorio experimental del plano de medios de la plataforma E-OVRT-VDP.

Este módulo implementa la ruta crítica de procesamiento visual:

- lectura de fuentes DBE;
- normalización de unidades visuales;
- inferencia open-vocabulary mediante adaptadores;
- postproceso de detecciones;
- publicación de evidencia perceptiva normalizada;
- instrumentación de métricas por corrida.

No implementa patrones de riesgo, alertas, notificaciones, UI ni plano de control.

## Quickstart

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
eovrt-media run --config configs/dbe_cr01_cr02_mock.yaml
```

## Modelos

Grounding DINO:

```bash
eovrt-media run --config configs/dbe_cr01_cr02_grounding_dino.yaml
```

YOLOE:

```bash
eovrt-media run --config configs/dbe_cr01_cr02_yoloe.yaml
```
```

---

## 24. Criterio de éxito del primer sprint

El primer sprint termina cuando se puede demostrar:

```text
Con una carpeta local de imágenes, el repo ejecuta una corrida DBE,
produce detecciones normalizadas y métricas,
y deja una carpeta runs/<run_id> reproducible.
```

Debe funcionar al menos con:

- `mock`;
- idealmente Grounding DINO tiny;
- YOLOE si el checkpoint está disponible.

---

## 25. Qué NO hacer en el primer sprint

No hacer:

- streaming;
- integración con cámaras;
- MediaMTX;
- arquitectura distribuida;
- plano de control;
- alertas;
- UI;
- tracking;
- zonas;
- fine-tuning;
- base de datos;
- colas;
- exportación ONNX/TensorRT;
- integración edge.

---

## 26. Integración futura con otros módulos

Este repo se integrará después con:

### Plano de control

Consumirá `DetectionEvent` y decidirá:

- estados de patrón;
- persistencia;
- confirmación;
- resolución;
- alerta interna.

### Soporte experimental

Consumirá:

- `summary.json`;
- `metrics.jsonl`;
- `errors.jsonl`;
- `effective_config.yaml`.

Permitirá comparar:

- modelos;
- prompts;
- umbrales;
- fuentes;
- hardware;
- políticas de muestreo.

### UI o inspección

Podrá consumir:

- previews;
- detecciones;
- resumen de corridas.

### Streaming / EBE

En una etapa posterior, `sources/` podrá sumar:

- `rtsp_source.py`;
- `webcam_source.py`;
- `mediamtx_source.py`;
- `gstreamer_source.py`.

Pero DBE debe quedar estable primero.

---

## 27. Glosario mínimo

### DBE

Dataset-Based Evaluation. Escenario de evaluación con imágenes/videos locales y reproducibles.

### EBE

Environment-Based Evaluation. Escenario con cámara o stream en entorno controlado.

### OVD

Open-Vocabulary Detection. Detección guiada por texto o prompts abiertos.

### VisualUnit

Unidad visual procesable: imagen o frame.

### DetectionEvent

Evento perceptivo normalizado producido por el plano de medios.

### MetricSample

Muestra técnica de medición del pipeline.

### RunConfig

Configuración declarativa de una corrida experimental.

### PromptSet

Conjunto versionado de prompts activos.

### Adapter

Capa que encapsula un modelo específico y lo adapta al contrato interno del repo.

---

## 28. Resumen ejecutivo para Codex

Implementar un repositorio Python simple llamado `eovrt-media-plane`.

Debe ejecutar corridas DBE locales con imágenes y luego video.  
Debe soportar `mock`, `grounding_dino` y `yoloe` como modelos mediante adaptadores.  
Debe leer prompts y parámetros desde YAML.  
Debe producir `detections.jsonl`, `metrics.jsonl`, `errors.jsonl`, `summary.json` y `effective_config.yaml`.  
Debe mantener una frontera estricta: **no patrones, no alertas, no plano de control**.  
El objetivo es producir evidencia perceptiva normalizada, trazable y medible para que otros módulos de la plataforma la consuman después.

---

## 29. Referencias técnicas rápidas

- Grounding DINO puede usarse desde Hugging Face Transformers con `AutoProcessor` y `AutoModelForZeroShotObjectDetection`.
- Para múltiples clases en Grounding DINO, separar conceptos con punto: `"person. safety helmet. reflective vest."`.
- YOLOE puede usarse desde Ultralytics con `YOLOE(...)` y `model.set_classes([...])`.
- Ultralytics se instala con `pip install -U ultralytics`.
- Los pesos de modelos no deben versionarse en Git.
- Si un checkpoint no descarga automáticamente, ubicarlo en `models/` y referenciarlo desde YAML.

---

## 30. Estado deseado luego del MVP del plano de medios

Al finalizar el MVP, debe ser posible ejecutar:

```bash
make run-mock
make run-gdino
make run-yoloe
```

Y obtener corridas comparables:

```text
runs/run_..._mock/
runs/run_..._grounding_dino/
runs/run_..._yoloe/
```

Cada corrida debe permitir responder:

- qué fuente se procesó;
- qué modelo se usó;
- qué prompts se usaron;
- qué umbrales se aplicaron;
- cuántas unidades visuales se procesaron;
- qué detecciones se produjeron;
- cuánto tardó cada tramo;
- cuántos errores hubo;
- qué configuración efectiva generó esos resultados.

Ese es el núcleo defendible del plano de medios.
