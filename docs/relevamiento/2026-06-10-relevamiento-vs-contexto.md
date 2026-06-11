# Relevamiento: plano de medios vs. documentación de contexto

**Fecha:** 2026-06-10
**Documentos de referencia:** `docs/contexto/context.md`, `docs/contexto/modelos-candidatos.md`, `docs/contexto/referencias-modelos.md`
**Alcance:** auditoría completa del código del repositorio contra el contexto, contratos, frontera arquitectónica, roadmap y matriz experimental descriptos en los documentos de contexto.

---

## Conclusión general

**El repositorio cumple sustancialmente con lo descripto (~95%).** La arquitectura, los contratos, los adaptadores, la CLI y la frontera de alcance están alineados con la documentación de contexto. Los seis hitos del roadmap están cubiertos (bootstrap, pipeline mock, Grounding DINO, YOLOE, video local e inspección de corridas). Se identificaron **2 faltantes concretos** y algunas desviaciones menores, ninguna bloqueante.

---

## Lo que cumple

### Contratos internos (§9 de context.md)

Los seis contratos existen como modelos Pydantic con todos los campos especificados:

- `RunConfig` (`src/eovrt_media/config/schemas.py`) con las 8 secciones: run, source, sampling, model, prompts, postprocess, outputs, logging.
- `VisualUnit` (`src/eovrt_media/contracts/visual_unit.py`) con run_id, unit_id, source_id, source_type, frame_index, timestamp_ms, width, height, path.
- `RawDetection` (`src/eovrt_media/contracts/detection.py`) con `raw` opcional no persistido por defecto.
- `DetectionEvent` (`src/eovrt_media/contracts/events.py`) con detecciones normalizadas: detection_id, label, prompt_id, confidence, bbox_xyxy, bbox_norm_xyxy, area_px.
- `MetricSample` (`src/eovrt_media/contracts/metrics.py`), incluido `gpu_memory_allocated_mb`.
- `ErrorEvent` (`src/eovrt_media/contracts/errors.py`) con stage, severity, message, recoverable.

Única diferencia: `DetectionEvent` usa sub-objetos anidados (`source`, `model`, `prompts`, `timing`) en vez de campos planos. Es consistente con lo que la documentación pide conceptualmente y mejora la validación.

### Adaptadores (§7 de context.md y referencias-modelos.md)

- Los tres adaptadores (`mock`, `grounding_dino`, `yoloe`) están detrás de `BaseDetectorAdapter` con factory en `src/eovrt_media/models/__init__.py`.
- Verificado por grep: `transformers`/`ultralytics`/`torch` no se importan fuera de los adaptadores. El único `torch` extra está en `metrics/collector.py` para medir VRAM, que la propia documentación pide.
- Grounding DINO usa `AutoProcessor` + `AutoModelForZeroShotObjectDetection` con `IDEA-Research/grounding-dino-tiny` y prompts concatenados con punto (`"person. safety helmet."`), exactamente como indica la referencia.
- YOLOE usa `yoloe-26s-seg.pt` (el checkpoint priorizado), llama `set_classes()` una sola vez por set de prompts, acepta ruta local o nombre remoto, y usa solo bounding boxes.
- No se inventaron nombres de checkpoints: los model_ids de las configs coinciden con los recomendados.

### Prompts (§8 de context.md)

- `configs/prompts/cr01_cr02_v1.yaml` versionado con `id`, `description`, `language`, `items` (id/text/role/enabled).
- Sin prompts hardcodeados en código.
- Los eventos y el summary preservan el `prompt_set_id` usado en la corrida.

### Pipeline, métricas y errores (§11 y §14 de context.md)

- `runtime/pipeline.py` implementa el flujo lineal de 19 pasos en orden.
- Cada etapa captura errores de forma independiente, registra en `errors.jsonl` con `recoverable` y continúa con la siguiente unidad.
- Latencias por tramo: read/preprocess/inference/postprocess/write/total (`metrics/timers.py`).
- Agregadas: FPS efectivo, promedio, p95, errores por etapa, VRAM (`metrics/collector.py`, `sinks/run_artifact_writer.py`).
- No se calculan métricas prohibidas para esta etapa (AP/mAP/precision/recall/F1/HOTA/MOTA).

### Frontera de alcance (§3 y §18 de context.md)

Sin violaciones: no hay lógica de riesgo, alertas, severidad semántica, MOT, zonas, streaming, base de datos, colas ni UI. `visualize.py` solo dibuja previews (cubierto por `save_previews` de la spec). Los pesos de modelos (≈1.3 GB bajo `models/`) **no** están versionados en git; el `.gitignore` cubre `models/**/*.pt|pth|safetensors|bin`.

### CLI, fuentes y configs (§13 de context.md)

- Los 4 comandos existen: `run`, `validate-config`, `inspect-run`, `download-models` (`src/eovrt_media/cli.py`).
- `ImageFolderSource` y `VideoFileSource` (con `frame_index`, `timestamp_ms` y sampling `every_n`/`target_fps`/`max_units`).
- Las 3 configs DBE existen: `dbe_cr01_cr02_mock.yaml`, `dbe_cr01_cr02_grounding_dino.yaml`, `dbe_cr01_cr02_yoloe.yaml`.

---

## Faltantes y desviaciones

| # | Hallazgo | Severidad | Detalle |
|---|----------|-----------|---------|
| 1 | **`run_manifest.json` no se genera** | Media | Es uno de los 8 artefactos por corrida del §10 (run_id, fecha de inicio, versión de código, archivos generados). No hay rastro en el código. Es el único artefacto faltante; los otros 7 están. |
| 2 | **`inspect-run` no muestra la latencia p95** | Baja | El Hito 6 pide mostrarla. El dato existe en `summary.json` (`p95_latency_ms`), pero `cli.py` solo imprime la latencia promedio. Fix de una línea. |
| 3 | Sin test dedicado de `RunArtifactWriter` | Baja | El §15 lo lista entre los tests mínimos. Está cubierto indirectamente por `test_pipeline_mock.py`, pero no tiene suite propia. |
| 4 | `docs/metrics.md` no existe | Baja | La estructura sugerida del §12 lo incluye. Sí existen `architecture.md`, `contracts.md`, `usage.md` y ADRs (estos últimos son un extra positivo). |
| 5 | `configs/experiments/` (matriz Y-E1…G-E4) no existe | Informativa | `modelos-candidatos.md` la define como exploración posterior, no requisito del MVP. El MVP pedido (mock + YOLOE + GDINO funcionales) está cubierto. Correctamente, el código no conoce los nombres `Y-E1`/`G-E1`. |
| 6 | Campos extra sobre la spec | Informativa | `RunConfig` agrega `name`, `active_ids`, flags granulares de outputs, `iou_threshold`, `image_size`; `VisualUnit` agrega `source_path` con sincronización automática. Son ampliaciones compatibles, no contradicen la documentación (que se declara no-cerrada). |

---

## Recomendaciones (en orden)

1. Implementar la escritura de `run_manifest.json` en `RunArtifactWriter`.
2. Agregar `p95_latency_ms` al output de `inspect-run`.
3. Crear test dedicado de `RunArtifactWriter`.
4. Escribir `docs/metrics.md` con la descripción de cada métrica.

Los puntos 1 y 2 son los únicos que tocan un criterio de aceptación explícito de la memoria de contexto.
