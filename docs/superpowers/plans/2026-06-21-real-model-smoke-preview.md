# Real Model Smoke Preview Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Render previews anotadas desde el pipeline productor/consumidor y ejecutar dos corridas DBE reales de diez imágenes en CUDA.

**Architecture:** `NormalizedUnit` conservará `source_path` para que el consumidor pueda renderizar detecciones ya reproyectadas sobre la imagen original. Las corridas reales usarán YAML temporales con el catálogo `bench_v2_val`, pesos locales y `run.max_units: 10`; no cambian catálogos ni el repositorio hermano.

**Tech Stack:** Python 3.14, Pydantic v2, OpenCV, PyTorch CUDA, Transformers, Ultralytics, pytest.

---

### Task 1: Propagar origen y generar previews anotadas

**Files:**
- Modify: `src/eovrt_media/contracts/normalized_unit.py`
- Modify: `src/eovrt_media/preprocessing/normalizer.py`
- Modify: `src/eovrt_media/runtime/pipeline.py`
- Modify: `tests/test_pipeline_mock.py`

- [ ] **Step 1: Escribir la prueba roja de preview materializada**

En `tests/test_pipeline_mock.py`, reemplazar la aserción de solo directorio por una preview legible:

```python
    def test_creates_annotated_preview(self, mock_config):
        run_id = run_pipeline(mock_config)
        previews_dir = Path(mock_config.output.base_dir) / run_id / "previews"
        previews = list(previews_dir.glob("*.preview.jpg"))
        assert previews
        assert cv2.imread(str(previews[0])) is not None
```

- [ ] **Step 2: Verificar que falla por ausencia de previews**

Run: `source .venv/bin/activate && pytest tests/test_pipeline_mock.py::TestPipelineMock::test_creates_annotated_preview -v`

Expected: FAIL porque `previews/` no contiene archivos `.preview.jpg`.

- [ ] **Step 3: Propagar `source_path` por el contrato normalizado**

Agregar al bloque de metadata de `NormalizedUnit`:

```python
    source_path: str | None = None
```

Y en el retorno de `normalize_spatial()`:

```python
        source_path=unit.path or unit.source_path,
```

- [ ] **Step 4: Renderizar desde el consumidor**

En `runtime/pipeline.py`, importar `draw_detections` y, después de escribir la detección,
agregar:

```python
                    if (
                        config.outputs.save_previews
                        and detections
                        and item.source_path
                        and item.frame_index is None
                        and run_context.units_processed < config.outputs.preview_max
                    ):
                        preview_path = run_context.run_dir / "previews" / f"{item.unit_id}.preview.jpg"
                        draw_detections(item.source_path, detections, preview_path)
```

La condición `frame_index is None` evita intentar leer un archivo de vídeo como una imagen;
el diseño de preview para frames se mantiene fuera de este cambio.

- [ ] **Step 5: Verificar la prueba y la suite**

Run: `source .venv/bin/activate && pytest tests/test_pipeline_mock.py -v && pytest -q && ruff check src tests`

Expected: PASS, sin errores de Ruff.

- [ ] **Step 6: Commit**

```bash
git add src/eovrt_media/contracts/normalized_unit.py src/eovrt_media/preprocessing/normalizer.py src/eovrt_media/runtime/pipeline.py tests/test_pipeline_mock.py
git commit -m "feat: render annotated image previews from pipeline"
```

### Task 2: Ejecutar DBE real con GDINO y YOLOE en CUDA

**Files:**
- Create: `/tmp/eovrt-gdino-cuda-smoke.yaml`
- Create: `/tmp/eovrt-yoloe-cuda-smoke.yaml`
- Read: `runs/<run_id>/{summary.json,detections.jsonl,metrics.jsonl,run_provenance.json,previews/}`

- [ ] **Step 1: Crear el YAML temporal de GDINO**

```yaml
run:
  scenario: DBE
  name: gdino_cuda_bench_v2_smoke
  max_units: 10
source:
  ref: bench_v2_val
model:
  ref: grounding-dino/gdino-tiny
  device: cuda
prompts:
  ref: cr01_cr02_v1
  active_ids: [person, helmet, vest]
outputs:
  run_dir: runs
  save_previews: true
  preview_max: 10
```

- [ ] **Step 2: Crear el YAML temporal de YOLOE**

```yaml
run:
  scenario: DBE
  name: yoloe_cuda_bench_v2_smoke
  max_units: 10
source:
  ref: bench_v2_val
model:
  ref: yoloe/yoloe-26s
  device: cuda
prompts:
  ref: cr01_cr02_v1
  active_ids: [person, helmet, vest]
outputs:
  run_dir: runs
  save_previews: true
  preview_max: 10
```

- [ ] **Step 3: Validar y ejecutar GDINO con acceso CUDA**

Run: `source .venv/bin/activate && eovrt-media validate-config --config /tmp/eovrt-gdino-cuda-smoke.yaml && eovrt-media run --config /tmp/eovrt-gdino-cuda-smoke.yaml`

Expected: resumen y artefactos bajo `runs/run_*_dbe_grounding_dino_deterministic/`.

- [ ] **Step 4: Validar y ejecutar YOLOE con acceso CUDA**

Run: `source .venv/bin/activate && eovrt-media validate-config --config /tmp/eovrt-yoloe-cuda-smoke.yaml && eovrt-media run --config /tmp/eovrt-yoloe-cuda-smoke.yaml`

Expected: resumen y artefactos bajo `runs/run_*_dbe_yoloe_deterministic/`.

- [ ] **Step 5: Inspeccionar y comprobar los artefactos de ambas corridas**

Para cada directorio de corrida:

```bash
eovrt-media inspect-run runs/<run_id>
test -s runs/<run_id>/summary.json
test -s runs/<run_id>/detections.jsonl
test -s runs/<run_id>/metrics.jsonl
test -s runs/<run_id>/run_provenance.json
find runs/<run_id>/previews -name '*.preview.jpg' -size +0c
```

Expected: diez líneas en `detections.jsonl` y `metrics.jsonl`; al menos una preview no vacía
si el modelo genera detecciones. Informar conteos, latencias, GPU y previews por modelo sin
interpretarlos como métricas de precisión.
