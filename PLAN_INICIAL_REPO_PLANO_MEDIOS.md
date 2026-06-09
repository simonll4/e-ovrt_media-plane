# Plan inicial del repositorio del plano de medios

**Proyecto:** E-OVRT-VDP  
**Repositorio propuesto:** `eovrt-media-plane`  
**Etapa:** inicio de implementación del plano de medios  
**Objetivo inmediato:** dejar un repositorio simple, ordenado y ejecutable para probar un pipeline mínimo DBE con Grounding DINO y YOLOE.

---

## 1. Objetivo del repositorio

El repositorio `eovrt-media-plane` debe contener únicamente la implementación inicial del **plano de medios** de la plataforma E-OVRT-VDP.

En esta primera versión, el objetivo no es construir todavía toda la plataforma, sino dejar un núcleo mínimo que permita:

1. Leer imágenes o videos locales.
2. Cargar prompts configurables para CR-01 y CR-02.
3. Ejecutar inferencia con un modelo OVD.
4. Probar al menos dos adaptadores de modelo:
   - Grounding DINO.
   - YOLOE.
5. Normalizar las detecciones a un formato común.
6. Guardar resultados en archivos reproducibles.
7. Medir latencia básica por imagen/frame.
8. Dejar una estructura preparada para extender luego hacia video, métricas, streaming, eventos y plano de control.

El repositorio **no debe implementar todavía**:

- Patrones de riesgo.
- Alertas.
- Persistencia de episodios.
- Motor de estados.
- UI.
- Streaming real.
- MediaMTX.
- Edge Node.
- MOT formal.
- Fine-tuning.
- Zonas o reglas espaciales complejas.

La salida principal del plano de medios será evidencia perceptiva normalizada. El plano de control, en otro repositorio o módulo futuro, será el encargado de interpretar esa evidencia como patrones, persistencia o alertas.

---

## 2. Decisión inicial de diseño

La implementación debe iniciar por **DBE: Dataset-Based Evaluation**, usando archivos locales. Esto reduce ruido técnico y permite validar primero la ruta crítica perceptiva.

La primera meta defendible es:

> Ejecutar una corrida local reproducible sobre imágenes o video, usando Grounding DINO o YOLOE, con prompts CR-01/CR-02, y producir detecciones normalizadas + métricas básicas.

---

## 3. Stack inicial recomendado

Para mantener el repositorio simple:

```txt
Python 3.11+
PyTorch
Transformers
Ultralytics
OpenCV
Pillow
Pydantic
PyYAML
Typer
Rich
pytest
ruff
```

### Dependencias principales

- `transformers`: para usar Grounding DINO mediante Hugging Face.
- `ultralytics`: para usar YOLOE mediante la API de Ultralytics.
- `torch` y `torchvision`: backend de inferencia.
- `opencv-python`: lectura de imágenes/video y previews.
- `Pillow`: compatibilidad con imágenes para modelos Hugging Face.
- `pydantic`: validación de configuración y contratos.
- `typer`: CLI simple.
- `rich`: logs legibles.
- `pytest`: tests mínimos.
- `ruff`: linting/formato.

---

## 4. Nombre y alcance del repositorio

### Nombre sugerido

```bash
eovrt-media-plane
```

### Descripción corta del repo

```txt
Plano de medios experimental para E-OVRT-VDP: lectura de fuentes visuales, inferencia open-vocabulary, normalización de detecciones y métricas básicas de corrida.
```

### README inicial

El README debe dejar clara la frontera:

```md
# E-OVRT-VDP Media Plane

Repositorio experimental del plano de medios de E-OVRT-VDP.

Este componente implementa la ruta crítica visual: lectura de fuentes DBE,
normalización de unidades visuales, inferencia open-vocabulary mediante adaptadores
de modelo, postproceso, persistencia de detecciones y métricas básicas.

No implementa patrones de riesgo, alertas, UI, notificaciones, MOT formal, zonas ni lógica de plano de control.
```

---

## 5. Estructura inicial del repositorio

La estructura debe quedar preparada pero simple. No conviene partir todavía en demasiados submódulos.

```txt
eovrt-media-plane/
│
├── README.md
├── pyproject.toml
├── .gitignore
├── .env.example
├── Makefile
│
├── configs/
│   ├── dbe_grounding_dino_cr01_cr02.yaml
│   ├── dbe_yoloe_cr01_cr02.yaml
│   └── prompts_cr01_cr02.yaml
│
├── data/
│   ├── samples/
│   │   ├── images/
│   │   │   └── .gitkeep
│   │   └── videos/
│   │       └── .gitkeep
│   └── README.md
│
├── models/
│   ├── README.md
│   ├── grounding-dino/
│   │   └── .gitkeep
│   └── yoloe/
│       └── .gitkeep
│
├── runs/
│   └── .gitkeep
│
├── docs/
│   ├── architecture.md
│   ├── contracts.md
│   ├── usage.md
│   └── decisions/
│       ├── ADR-0001-repo-scope.md
│       ├── ADR-0002-dbe-first.md
│       └── ADR-0003-model-adapters.md
│
├── scripts/
│   ├── bootstrap.sh
│   ├── download_models.sh
│   ├── run_grounding_dino_sample.sh
│   └── run_yoloe_sample.sh
│
├── src/
│   └── eovrt_media/
│       ├── __init__.py
│       ├── cli.py
│       ├── config.py
│       ├── contracts.py
│       ├── pipeline.py
│       ├── sources.py
│       ├── sinks.py
│       ├── metrics.py
│       ├── visualize.py
│       └── adapters/
│           ├── __init__.py
│           ├── base.py
│           ├── grounding_dino_hf.py
│           └── yoloe_ultralytics.py
│
└── tests/
    ├── test_config.py
    ├── test_contracts.py
    ├── test_sources.py
    └── test_pipeline_mock.py
```

### Por qué esta estructura

- `configs/`: toda corrida debe nacer de configuración, no de valores hardcodeados.
- `data/samples/`: sólo muestras pequeñas para probar el pipeline.
- `models/`: pesos locales descargados, no versionados.
- `runs/`: salidas de corridas, no versionadas.
- `docs/`: documentación técnica mínima desde el primer commit.
- `scripts/`: comandos reproducibles para bootstrap, descarga y pruebas.
- `src/eovrt_media/`: implementación del paquete.
- `adapters/`: cada modelo se conecta mediante una interfaz común.

---

## 6. Archivos que deben ignorarse en Git

`.gitignore` recomendado:

```gitignore
# Python
__pycache__/
*.py[cod]
.pytest_cache/
.ruff_cache/
.mypy_cache/
.venv/
venv/

# Env
.env

# Modelos y datasets pesados
models/**/*.pt
models/**/*.pth
models/**/*.safetensors
models/**/*.bin
models/**/blobs/
models/**/snapshots/
models/**/refs/
data/raw/
data/datasets/

# Corridas experimentales
runs/*
!runs/.gitkeep

# Previews generadas
*.preview.jpg
*.annotated.jpg

# OS/IDE
.DS_Store
.idea/
.vscode/
```

---

## 7. Inicialización del repositorio

### 7.1. Crear el repo

```bash
mkdir eovrt-media-plane
cd eovrt-media-plane
git init
```

### 7.2. Crear estructura base

```bash
mkdir -p configs
mkdir -p data/samples/images data/samples/videos
mkdir -p models/grounding-dino models/yoloe
mkdir -p runs
mkdir -p docs/decisions
mkdir -p scripts
mkdir -p src/eovrt_media/adapters
mkdir -p tests

touch data/samples/images/.gitkeep
touch data/samples/videos/.gitkeep
touch models/grounding-dino/.gitkeep
touch models/yoloe/.gitkeep
touch runs/.gitkeep
touch src/eovrt_media/__init__.py
touch src/eovrt_media/adapters/__init__.py
```

---

## 8. Entorno Python

### 8.1. Crear entorno virtual

```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip setuptools wheel
```

### 8.2. Instalar PyTorch

Para CUDA, instalar según la versión real del driver/NVIDIA disponible. Ejemplo genérico:

```bash
pip install torch torchvision --index-url https://download.pytorch.org/whl/cu121
```

Para CPU:

```bash
pip install torch torchvision
```

### 8.3. Instalar dependencias del proyecto

```bash
pip install transformers accelerate pillow opencv-python pydantic pyyaml typer rich pytest ruff huggingface_hub ultralytics
```

---

## 9. `pyproject.toml` inicial

```toml
[project]
name = "eovrt-media-plane"
version = "0.1.0"
description = "Experimental media plane for E-OVRT-VDP"
requires-python = ">=3.11"
dependencies = [
    "torch",
    "torchvision",
    "transformers",
    "accelerate",
    "pillow",
    "opencv-python",
    "pydantic",
    "pyyaml",
    "typer",
    "rich",
    "huggingface_hub",
    "ultralytics",
]

[project.optional-dependencies]
dev = [
    "pytest",
    "ruff",
]

[project.scripts]
eovrt-media = "eovrt_media.cli:app"

[tool.ruff]
line-length = 100
target-version = "py311"

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["src"]
```

Instalar editable:

```bash
pip install -e ".[dev]"
```

---

## 10. Configuración inicial de prompts

Archivo: `configs/prompts_cr01_cr02.yaml`

```yaml
version: cr01_cr02_v1
items:
  - id: person
    text: "person"
    aliases:
      - "worker"
      - "construction worker"

  - id: helmet
    text: "safety helmet"
    aliases:
      - "hard hat"
      - "construction helmet"

  - id: vest
    text: "high visibility safety vest"
    aliases:
      - "reflective vest"
      - "safety vest"
```

En esta primera versión, los prompts deben usarse para detectar entidades visuales básicas. La interpretación “persona sin casco” o “persona sin chaleco” queda fuera del plano de medios y se resolverá más adelante en el plano de control.

---

## 11. Configuración de corrida con Grounding DINO

Archivo: `configs/dbe_grounding_dino_cr01_cr02.yaml`

```yaml
run:
  scenario: DBE
  name: dbe_grounding_dino_cr01_cr02
  seed: 42

source:
  type: image_folder
  path: data/samples/images
  extensions: [".jpg", ".jpeg", ".png"]

model:
  adapter: grounding_dino_hf
  model_id: IDEA-Research/grounding-dino-tiny
  local_dir: models/grounding-dino/grounding-dino-tiny
  device: cuda
  box_threshold: 0.35
  text_threshold: 0.25

prompts:
  file: configs/prompts_cr01_cr02.yaml
  active_ids: ["person", "helmet", "vest"]

output:
  base_dir: runs
  save_jsonl: true
  save_summary: true
  save_previews: true
```

---

## 12. Configuración de corrida con YOLOE

Archivo: `configs/dbe_yoloe_cr01_cr02.yaml`

```yaml
run:
  scenario: DBE
  name: dbe_yoloe_cr01_cr02
  seed: 42

source:
  type: image_folder
  path: data/samples/images
  extensions: [".jpg", ".jpeg", ".png"]

model:
  adapter: yoloe_ultralytics
  weights: models/yoloe/yoloe-26s-seg.pt
  device: cuda
  confidence_threshold: 0.25
  iou_threshold: 0.50

prompts:
  file: configs/prompts_cr01_cr02.yaml
  active_ids: ["person", "helmet", "vest"]

output:
  base_dir: runs
  save_jsonl: true
  save_summary: true
  save_previews: true
```

---

## 13. Descarga de modelos

Archivo: `scripts/download_models.sh`

```bash
#!/usr/bin/env bash
set -euo pipefail

mkdir -p models/grounding-dino/grounding-dino-tiny
mkdir -p models/yoloe

printf "\n[1/2] Descargando Grounding DINO tiny desde Hugging Face...\n"
huggingface-cli download IDEA-Research/grounding-dino-tiny \
  --local-dir models/grounding-dino/grounding-dino-tiny

printf "\n[2/2] Preparando YOLOE small desde Ultralytics...\n"
python - <<'PY'
from pathlib import Path
from ultralytics import YOLOE

out_dir = Path("models/yoloe")
out_dir.mkdir(parents=True, exist_ok=True)

# Ultralytics descarga automáticamente el checkpoint si no existe localmente.
model = YOLOE("yoloe-26s-seg.pt")

# Si el archivo queda en el directorio actual, se mueve a models/yoloe.
src = Path("yoloe-26s-seg.pt")
dst = out_dir / "yoloe-26s-seg.pt"
if src.exists() and not dst.exists():
    src.rename(dst)

print("YOLOE listo")
PY

printf "\nModelos preparados.\n"
```

Dar permisos:

```bash
chmod +x scripts/download_models.sh
```

Ejecutar:

```bash
./scripts/download_models.sh
```

### Nota sobre YOLOE

Si Ultralytics cambia el mecanismo de descarga o el nombre del checkpoint, usar el mecanismo oficial vigente de Ultralytics. Para el arranque conviene usar el modelo pequeño (`yoloe-26s-seg.pt`) por consumo de VRAM y tiempo de prueba.

---

## 14. Contratos mínimos

Archivo: `src/eovrt_media/contracts.py`

### 14.1. `VisualUnit`

Representa una imagen o frame procesable.

Campos mínimos:

```python
unit_id: str
source_path: str
source_type: str
frame_index: int | None
width: int
height: int
timestamp_ms: float | None
```

### 14.2. `Detection`

Representa una detección normalizada.

Campos mínimos:

```python
label: str
prompt_id: str | None
confidence: float
bbox_xyxy: list[float]
bbox_norm_xyxy: list[float]
model_name: str
```

### 14.3. `DetectionEvent`

Evento principal del plano de medios.

Campos mínimos:

```python
run_id: str
unit_id: str
source_path: str
model_adapter: str
prompt_version: str
detections: list[Detection]
timing_ms: dict[str, float]
```

### 14.4. `RunSummary`

Resumen de corrida.

Campos mínimos:

```python
run_id: str
scenario: str
model_adapter: str
source_count: int
units_processed: int
units_failed: int
avg_latency_ms: float
started_at: str
finished_at: str
```

---

## 15. Interfaz común de adaptadores

Archivo: `src/eovrt_media/adapters/base.py`

```python
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from PIL import Image


@dataclass
class RawDetection:
    label: str
    score: float
    box_xyxy: list[float]


class BaseDetectorAdapter(ABC):
    @abstractmethod
    def load(self) -> None:
        pass

    @abstractmethod
    def predict(self, image: Image.Image | Path, prompts: list[str]) -> list[RawDetection]:
        pass

    def close(self) -> None:
        pass
```

El pipeline sólo debe depender de `BaseDetectorAdapter`. Nunca debe depender directamente de `transformers`, `GroundingDINO`, `ultralytics` o `YOLOE`.

---

## 16. Adaptador Grounding DINO inicial

Archivo: `src/eovrt_media/adapters/grounding_dino_hf.py`

Responsabilidad:

1. Cargar `AutoProcessor`.
2. Cargar `AutoModelForZeroShotObjectDetection`.
3. Recibir imagen + prompts.
4. Ejecutar inferencia.
5. Convertir salida a `RawDetection`.

Pseudocódigo:

```python
class GroundingDinoHFAdapter(BaseDetectorAdapter):
    def __init__(self, model_id, device, box_threshold, text_threshold):
        ...

    def load(self):
        self.processor = AutoProcessor.from_pretrained(self.model_id)
        self.model = AutoModelForZeroShotObjectDetection.from_pretrained(self.model_id).to(self.device)
        self.model.eval()

    def predict(self, image, prompts):
        text_labels = [prompts]
        inputs = self.processor(images=image, text=text_labels, return_tensors="pt").to(self.device)
        with torch.no_grad():
            outputs = self.model(**inputs)
        results = self.processor.post_process_grounded_object_detection(
            outputs,
            inputs.input_ids,
            threshold=self.box_threshold,
            text_threshold=self.text_threshold,
            target_sizes=[image.size[::-1]],
        )[0]
        return normalize_results(results)
```

---

## 17. Adaptador YOLOE inicial

Archivo: `src/eovrt_media/adapters/yoloe_ultralytics.py`

Responsabilidad:

1. Cargar checkpoint `.pt`.
2. Configurar clases con `set_classes()`.
3. Ejecutar inferencia.
4. Convertir salida de Ultralytics a `RawDetection`.

Pseudocódigo:

```python
class YOLOEUltralyticsAdapter(BaseDetectorAdapter):
    def __init__(self, weights, device, confidence_threshold, iou_threshold):
        ...

    def load(self):
        self.model = YOLOE(self.weights)

    def predict(self, image_path, prompts):
        self.model.set_classes(prompts)
        results = self.model.predict(
            source=str(image_path),
            conf=self.confidence_threshold,
            iou=self.iou_threshold,
            device=self.device,
            verbose=False,
        )
        return normalize_results(results[0])
```

Para optimizar después, `set_classes()` no debería ejecutarse en cada imagen si los prompts no cambian. En el primer pipeline simple se puede aceptar; luego debe moverse a `load()` o a una etapa `configure_prompts()`.

---

## 18. Pipeline mínimo

Archivo: `src/eovrt_media/pipeline.py`

Flujo inicial:

```txt
RunConfig
  ↓
ImageFolderSource
  ↓
VisualUnit
  ↓
ModelAdapter.predict()
  ↓
Detection normalizado
  ↓
JSONL sink
  ↓
Summary
```

### Salidas por corrida

Cada ejecución debe crear:

```txt
runs/<run_id>/
├── effective_config.yaml
├── detections.jsonl
├── metrics.jsonl
├── summary.json
└── previews/
    └── *.jpg
```

### Ejemplo de `detections.jsonl`

```json
{"run_id":"20260609_001","unit_id":"img_000001","source_path":"data/samples/images/test.jpg","model_adapter":"grounding_dino_hf","detections":[{"label":"person","prompt_id":"person","confidence":0.84,"bbox_xyxy":[120,80,400,700],"bbox_norm_xyxy":[0.09,0.11,0.31,0.97]}],"timing_ms":{"total":112.4,"inference":101.7}}
```

### Ejemplo de `summary.json`

```json
{
  "run_id": "20260609_001",
  "scenario": "DBE",
  "model_adapter": "grounding_dino_hf",
  "source_count": 12,
  "units_processed": 12,
  "units_failed": 0,
  "avg_latency_ms": 118.3,
  "started_at": "2026-06-09T10:00:00Z",
  "finished_at": "2026-06-09T10:00:08Z"
}
```

---

## 19. CLI mínima

Archivo: `src/eovrt_media/cli.py`

Comando principal:

```bash
eovrt-media run --config configs/dbe_grounding_dino_cr01_cr02.yaml
```

Comandos deseables:

```bash
eovrt-media run --config configs/dbe_grounding_dino_cr01_cr02.yaml

eovrt-media run --config configs/dbe_yoloe_cr01_cr02.yaml

eovrt-media inspect-run runs/<run_id>
```

Para esta primera versión basta con `run`.

---

## 20. Scripts de ejecución rápida

### `scripts/run_grounding_dino_sample.sh`

```bash
#!/usr/bin/env bash
set -euo pipefail
source .venv/bin/activate
eovrt-media run --config configs/dbe_grounding_dino_cr01_cr02.yaml
```

### `scripts/run_yoloe_sample.sh`

```bash
#!/usr/bin/env bash
set -euo pipefail
source .venv/bin/activate
eovrt-media run --config configs/dbe_yoloe_cr01_cr02.yaml
```

Permisos:

```bash
chmod +x scripts/run_grounding_dino_sample.sh
chmod +x scripts/run_yoloe_sample.sh
```

---

## 21. Makefile inicial

Archivo: `Makefile`

```makefile
.PHONY: install lint test download-models run-gdino run-yoloe

install:
	python -m pip install --upgrade pip setuptools wheel
	pip install -e ".[dev]"

lint:
	ruff check src tests

test:
	pytest -q

download-models:
	./scripts/download_models.sh

run-gdino:
	./scripts/run_grounding_dino_sample.sh

run-yoloe:
	./scripts/run_yoloe_sample.sh
```

---

## 22. Documentación mínima

### `docs/architecture.md`

Debe explicar:

- Qué es el plano de medios.
- Qué entra y qué sale.
- Por qué DBE primero.
- Por qué los modelos se integran por adaptadores.
- Qué queda fuera del repo.

### `docs/contracts.md`

Debe describir:

- `VisualUnit`.
- `Detection`.
- `DetectionEvent`.
- `MetricSample`.
- `RunSummary`.

### `docs/usage.md`

Debe incluir:

- Instalación.
- Descarga de modelos.
- Dónde poner imágenes.
- Cómo ejecutar Grounding DINO.
- Cómo ejecutar YOLOE.
- Cómo leer resultados.

---

## 23. ADRs iniciales

### `ADR-0001-repo-scope.md`

```md
# ADR-0001: Repositorio dedicado al plano de medios

## Estado
Aceptada

## Contexto
La arquitectura de E-OVRT-VDP separa plano de medios y plano de control.

## Decisión
Implementar el plano de medios en un repositorio separado llamado `eovrt-media-plane`.

## Incluye
- Lectura de fuentes visuales.
- Inferencia OVD.
- Normalización de detecciones.
- Métricas básicas.
- Persistencia experimental de resultados.

## Excluye
- Patrones de riesgo.
- Alertas.
- UI.
- Notificaciones.
- MOT formal.
- Zonas.
- Fine-tuning.

## Consecuencias
El plano de control consumirá evidencia perceptiva normalizada generada por este repositorio.
```

### `ADR-0002-dbe-first.md`

```md
# ADR-0002: DBE como primer escenario de implementación

## Estado
Aceptada

## Contexto
El sistema debe estabilizar la ruta crítica perceptiva antes de incorporar streaming, cámaras o edge nodes.

## Decisión
La primera implementación se hará sobre imágenes y videos locales en modo DBE.

## Consecuencias
Se reduce complejidad inicial y se obtiene una base reproducible para comparar modelos, prompts y métricas.
```

### `ADR-0003-model-adapters.md`

```md
# ADR-0003: Integración de modelos mediante adaptadores

## Estado
Aceptada

## Contexto
El proyecto debe comparar modelos OVD sin acoplar el pipeline a una implementación concreta.

## Decisión
Cada modelo se integrará mediante un adaptador que implemente una interfaz común.

## Consecuencias
Grounding DINO, YOLOE y futuros modelos podrán intercambiarse desde configuración.
```

---

## 24. Orden de implementación sugerido

### Hito 1: repo mínimo ejecutable

Objetivo:

```txt
El repo instala, corre tests y ejecuta un comando vacío o mock.
```

Tareas:

1. Crear estructura.
2. Crear `pyproject.toml`.
3. Crear CLI con `eovrt-media --help`.
4. Crear README inicial.
5. Crear `.gitignore`.
6. Crear Makefile.
7. Primer commit.

Criterio de aceptación:

```bash
pip install -e ".[dev]"
eovrt-media --help
pytest
```

---

### Hito 2: lectura de imágenes + contratos

Objetivo:

```txt
Leer una carpeta de imágenes y crear VisualUnit por cada imagen.
```

Tareas:

1. Implementar `config.py`.
2. Implementar `contracts.py`.
3. Implementar `sources.py` con `ImageFolderSource`.
4. Testear lectura de imágenes.

Criterio de aceptación:

```bash
eovrt-media run --config configs/dbe_grounding_dino_cr01_cr02.yaml
```

Debe listar imágenes aunque todavía no haya modelo real.

---

### Hito 3: pipeline con detector mock

Objetivo:

```txt
Validar todo el flujo sin depender de GPU ni modelos pesados.
```

Tareas:

1. Crear `MockDetectorAdapter` opcional.
2. Generar detecciones falsas.
3. Guardar `detections.jsonl`.
4. Guardar `summary.json`.
5. Agregar tests de pipeline.

Criterio de aceptación:

```txt
runs/<run_id>/detections.jsonl existe y tiene eventos válidos.
```

---

### Hito 4: integración Grounding DINO

Objetivo:

```txt
Ejecutar Grounding DINO sobre imágenes locales con prompts CR-01/CR-02.
```

Tareas:

1. Implementar `GroundingDinoHFAdapter`.
2. Descargar `IDEA-Research/grounding-dino-tiny`.
3. Probar prompts: `person`, `safety helmet`, `high visibility safety vest`.
4. Normalizar detecciones.
5. Guardar previews anotadas.

Criterio de aceptación:

```bash
make run-gdino
```

Debe generar:

```txt
runs/<run_id>/detections.jsonl
runs/<run_id>/summary.json
runs/<run_id>/previews/*.jpg
```

---

### Hito 5: integración YOLOE

Objetivo:

```txt
Ejecutar YOLOE sobre las mismas imágenes y producir el mismo contrato de salida.
```

Tareas:

1. Implementar `YOLOEUltralyticsAdapter`.
2. Descargar/preparar `yoloe-26s-seg.pt`.
3. Configurar prompts con `set_classes()`.
4. Convertir resultados de Ultralytics a `Detection` normalizado.
5. Guardar previews.

Criterio de aceptación:

```bash
make run-yoloe
```

La salida debe tener el mismo formato que Grounding DINO.

---

### Hito 6: comparación mínima de modelos

Objetivo:

```txt
Comparar tiempos básicos y cantidad de detecciones entre ambos modelos.
```

Tareas:

1. Agregar `metrics.jsonl`.
2. Medir:
   - tiempo de carga del modelo,
   - tiempo de inferencia por imagen,
   - tiempo total por imagen,
   - cantidad de detecciones.
3. Agregar resumen por corrida.

Criterio de aceptación:

```txt
summary.json incluye avg_latency_ms, p50_latency_ms y p95_latency_ms.
```

---

## 25. Convención de salidas normalizadas

Todas las detecciones deben salir en formato `xyxy` absoluto y normalizado.

```json
{
  "label": "person",
  "prompt_id": "person",
  "confidence": 0.84,
  "bbox_xyxy": [120.0, 80.0, 400.0, 700.0],
  "bbox_norm_xyxy": [0.093, 0.111, 0.312, 0.972],
  "model_name": "grounding_dino_hf"
}
```

Reglas:

1. `bbox_xyxy` siempre en píxeles.
2. `bbox_norm_xyxy` siempre entre 0 y 1.
3. `label` debe ser el texto devuelto o mapeado por el modelo.
4. `prompt_id` debe mapearse contra `prompts_cr01_cr02.yaml` cuando sea posible.
5. `confidence` siempre entre 0 y 1.
6. Si el modelo devuelve máscaras, ignorarlas por ahora o guardarlas como campo opcional futuro. El MVP del plano de medios debe centrarse en bounding boxes.

---

## 26. Datos sample para probar

Crear carpeta:

```txt
data/samples/images/
```

Agregar entre 5 y 20 imágenes pequeñas para prueba manual. Idealmente:

- Persona con casco.
- Persona sin casco.
- Persona con chaleco.
- Persona sin chaleco.
- Escena de obra con varias personas.
- Imagen sin personas para validar falsos positivos.

No subir datasets pesados al repo. Para datasets reales usar `data/raw/` o `data/datasets/`, ignorados por Git.

---

## 27. Reglas de diseño para no desordenar el repo

1. No hardcodear prompts dentro del adaptador.
2. No hardcodear rutas de modelos dentro del código.
3. No mezclar detección con alerta.
4. No implementar CR-01/CR-02 como patrón todavía.
5. No acoplar el pipeline a Grounding DINO ni YOLOE.
6. No guardar videos o datasets pesados en Git.
7. No versionar pesos de modelos.
8. No optimizar con TensorRT hasta tener baseline medido.
9. No agregar streaming hasta tener DBE estable.
10. Todo experimento debe dejar `effective_config.yaml`, `detections.jsonl` y `summary.json`.

---

## 28. Primeros issues recomendados

### Issue 1: Inicializar repo base

```md
Crear estructura inicial del repositorio, pyproject, README, .gitignore, Makefile y CLI mínima.

Criterios:
- `pip install -e .[dev]` funciona.
- `eovrt-media --help` funciona.
- `pytest` corre sin errores.
```

### Issue 2: Implementar configuración y prompts

```md
Agregar carga de configuración YAML y archivo de prompts CR-01/CR-02.

Criterios:
- Se carga `dbe_grounding_dino_cr01_cr02.yaml`.
- Se carga `dbe_yoloe_cr01_cr02.yaml`.
- Se validan prompts activos.
```

### Issue 3: Implementar ImageFolderSource

```md
Leer imágenes desde carpeta y construir VisualUnit.

Criterios:
- Soporta jpg, jpeg y png.
- Ignora archivos no soportados.
- Falla con mensaje claro si la carpeta no existe.
```

### Issue 4: Implementar pipeline con MockDetector

```md
Crear pipeline completo usando un detector falso.

Criterios:
- Genera `runs/<run_id>/detections.jsonl`.
- Genera `runs/<run_id>/summary.json`.
- Tiene tests unitarios.
```

### Issue 5: Integrar Grounding DINO

```md
Agregar adaptador GroundingDinoHFAdapter usando Transformers.

Criterios:
- Carga `IDEA-Research/grounding-dino-tiny`.
- Detecta prompts configurados.
- Normaliza bounding boxes.
- Genera previews.
```

### Issue 6: Integrar YOLOE

```md
Agregar adaptador YOLOEUltralyticsAdapter usando Ultralytics.

Criterios:
- Carga `yoloe-26s-seg.pt`.
- Configura clases con prompts.
- Normaliza bounding boxes.
- Genera previews.
```

### Issue 7: Métricas básicas

```md
Medir latencia y resumen de corrida.

Criterios:
- `summary.json` incluye cantidad de imágenes, promedio de latencia, p50, p95 y errores.
- `metrics.jsonl` tiene una línea por imagen procesada.
```

---

## 29. Comandos finales esperados

Instalación:

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip setuptools wheel
pip install -e ".[dev]"
```

Descarga de modelos:

```bash
make download-models
```

Ejecutar Grounding DINO:

```bash
make run-gdino
```

Ejecutar YOLOE:

```bash
make run-yoloe
```

Ver resultados:

```bash
ls runs/
cat runs/<run_id>/summary.json
head runs/<run_id>/detections.jsonl
```

---

## 30. Resultado esperado del primer sprint

Al terminar esta inicialización, el repositorio debería permitir demostrar:

1. El plano de medios existe como componente separado.
2. El pipeline DBE mínimo funciona.
3. Grounding DINO y YOLOE pueden probarse desde configuración.
4. Ambos modelos producen el mismo contrato de salida.
5. Se generan evidencias reproducibles por corrida.
6. El código queda listo para extender luego a video local, métricas más completas, streaming y conexión futura con el plano de control.

La entrega mínima defendible no es una alerta de riesgo, sino una ruta perceptiva reproducible:

```txt
fuente visual local → modelo OVD → detecciones normalizadas → métricas → artefactos de corrida
```

---

## 31. Referencias técnicas a revisar durante implementación

- Grounding DINO oficial: repositorio IDEA-Research/GroundingDINO.
- Grounding DINO en Hugging Face Transformers: `AutoProcessor` + `AutoModelForZeroShotObjectDetection`.
- Modelo Hugging Face sugerido para primera prueba: `IDEA-Research/grounding-dino-tiny`.
- YOLOE oficial: repositorio THU-MIG/yoloe.
- YOLOE en Ultralytics: API `YOLOE`, checkpoints `yoloe-26s/m/l-seg.pt`, `set_classes()` para prompts textuales.
- Ultralytics Quickstart: instalación con `pip install -U ultralytics`.

---

## 32. Próximo paso concreto

Ejecutar este orden:

```bash
mkdir eovrt-media-plane
cd eovrt-media-plane
git init
# crear estructura
# crear pyproject.toml
# crear CLI mínima
# instalar editable
# probar eovrt-media --help
# agregar configs
# agregar detector mock
# recién después integrar Grounding DINO
# luego integrar YOLOE
```

Primer commit recomendado:

```bash
git add .
git commit -m "chore: initialize media plane repository structure"
```

Segundo commit recomendado:

```bash
git commit -m "feat: add DBE pipeline with image folder source and mock detector"
```

Tercer commit recomendado:

```bash
git commit -m "feat: add Grounding DINO adapter"
```

Cuarto commit recomendado:

```bash
git commit -m "feat: add YOLOE adapter"
```
