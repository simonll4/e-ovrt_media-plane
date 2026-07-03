# Salida de video anotado

**Fecha**: 2026-06-30
**Repo**: e-ovrt_media-plane
**Estado**: aprobado (brainstorming)

## Problema

El pipeline produce previews JPG por-frame (`runs/<id>/previews/`), pero topadas a
`preview_max` (20) y a resolución del payload. No existe forma de obtener un **video
anotado** continuo de una corrida, que es lo que se necesita para demostrar el pipeline
sobre un clip real (`data/samples/videos/recorte-1.mp4`).

## Decisiones de diseño (acordadas)

- **Frames de origen**: el `payload` ya cargado en memoria (resolución de input del
  modelo) + `raw_detections` (mismo espacio). Reusa la lógica de dibujo existente. No se
  re-leen frames del `.mp4`.
- **Alcance**: single-host **y** two-node. Cubierto por una sola implementación porque
  `run_consumer_loop` (en `runtime/pipeline.py`) es compartido por `run_pipeline` y
  `run_node_b`.
- **Frames incluidos**: todos los que pasan el rate-gate (stride), sin tope de
  `preview_max`.
- **FPS de salida**: `fps_origen / stride`. Se infiere del delta de `timestamp_ms` entre
  los dos primeros units; override explícito vía config.

## Componentes

### 1. Config — `config/schemas.py: OutputsConfig`

Dos campos nuevos, opt-in (default no cambia el comportamiento actual):

```python
save_annotated_video: bool = False
video_fps: float | None = None   # override; si None, se infiere
```

### 2. `visualize.py` — refactor para reuso

Extraer un helper puro que devuelve el frame BGR anotado:

```python
def annotate_payload_bgr(image_rgb, detections) -> np.ndarray
```

Contiene la conversión float/uint8 → RGB → BGR + `_draw_annotations` que hoy vive dentro
de `draw_detections_rgb`. `draw_detections_rgb` se reescribe para llamarlo y luego
`_write_preview`. **Sin cambio de comportamiento observable en previews.**

### 3. `sinks/video_annotation_writer.py` — `VideoAnnotationWriter` (nuevo)

Responsabilidad única: acumular frames anotados y escribir un `.mp4`.

- **Init**: recibe `output_path`, `fps_override: float | None`, `default_fps` (=10.0).
- **`add(image_rgb, detections, timestamp_ms)`**:
  - Anota con `annotate_payload_bgr`.
  - **Apertura diferida del `cv2.VideoWriter`**:
    - Si `fps_override` está seteado → abre en el primer frame con ese fps.
    - Si no → buffer de **un** frame; al llegar el segundo, computa
      `fps = 1000.0 / (ts2 - ts1)` (si `ts2 - ts1 <= 0` → `default_fps`), abre, y escribe
      ambos frames.
  - Codec `mp4v`, tamaño = el del primer frame anotado.
  - Frames de tamaño distinto al de apertura se reescalan (`cv2.resize`) a ese tamaño.
- **`close()`**: si quedó un frame bufferizado sin abrir (corrida de 1 frame), abre con
  `default_fps` y lo escribe; libera el `VideoWriter`. Idempotente.

### 4. Wiring — `runtime/pipeline.py: run_consumer_loop`

- Antes del `while`: `video_writer = VideoAnnotationWriter(run_dir/"annotated.mp4", ...)`
  si `config.outputs.save_annotated_video`, else `None`. Envolver el bucle en
  `try/finally` con `video_writer.close()` en el `finally`.
- Junto al bloque de preview existente (mismo `raw_detections`, mismo `item.payload`):
  ```python
  if video_writer is not None:
      try:
          video_writer.add(item.payload, raw_detections, item.timestamp_ms)
      except Exception as exc:
          artifact_writer.write_error(ErrorEvent(stage="annotated_video", recoverable=True, ...))
  ```
  Independiente del contador `preview_attempts` (sin tope).

## Ejecución de `recorte-1.mp4`

- `configs/datasets/video_sample.yaml`: `path` → `data/samples/videos/recorte-1.mp4`.
- `experiments/video_annotated.yaml` (repo experimental-setup): `source.ref: video_sample`,
  `model.ref: yoloe/yoloe-26s`, `prompts.ref: cr01_cr02_v2_short` con
  `active_ids: [person, helmet, vest]`, `rate_control.stride: <N>`, y
  `outputs: { save_annotated_video: true }`.

## Manejo de errores

Cada `add()` falla aislado → `errors.jsonl` (stage `annotated_video`, `recoverable=true`),
la corrida continúa. `close()` siempre corre vía `finally`.

## Tests

- `VideoAnnotationWriter`: inferencia de fps desde timestamps, override explícito,
  corrida de un solo frame (usa `default_fps`), reescalado de frame disímil, archivo
  `.mp4` generado y legible.
- `annotate_payload_bgr`: dtype float y uint8, forma de salida BGR.
- Integración: corrida con `MockDetector` y `save_annotated_video=true` produce
  `annotated.mp4` no vacío y `previews/` sin regresión.

## Fuera de alcance

Anotación a resolución original, overlays de tracking/zonas, otros codecs, GIF/streaming.
