# Diseño — Optimización de rendimiento del Media Plane (WS1 inferencia + WS2 transporte)

- **Fecha:** 2026-06-22
- **Alcance de este ciclo:** rendimiento de inferencia (WS1) y de transporte de red (WS2).
- **Fuera de alcance (ciclos propios):** robustez (estado de corrida, frescura granular), organización (limpieza de compatibilidad de esquemas, salidas configurables, tests de throughput), cierre del núcleo validable (video anotado, diagnósticos de postproceso).
- **Hardware objetivo:** GPU NVIDIA RTX 4060 laptop (CUDA, 8 GB VRAM).

## 1. Objetivo

Mejorar el rendimiento del pipeline perceptivo sin alterar contratos ni el modelo de frescura,
manteniendo la separación Media/Control Plane. Las optimizaciones deben ser configurables,
degradar con elegancia cuando no hay CUDA, y ser verificables contra el BENCH para descartar
regresión de precisión.

## 2. Decisiones tomadas (brainstorming)

- **Batching:** fuera de este ciclo. Se mantiene 1 imagen por inferencia.
- **fp16:** sí, configurable, default activo en CUDA.
- **Compresión de transporte:** JPEG, calidad configurable. Se mantiene el patrón ZeroMQ REQ/REP
  (el modelo de pull sirve a la política de frescura; no se reemplaza).
- **Medición:** sin infraestructura nueva de tests; se usan las métricas existentes
  (`p50/p95/p99`, `fps_effective` en `summary.json`) comparando antes/después.

## 3. Correcciones a la auditoría inicial (anclaje al código real)

Verificado leyendo `models/yoloe_adapter.py`, `models/grounding_dino_adapter.py`,
`transport/serialization.py`:

- **YOLOE ya corre en inference mode** internamente vía Ultralytics `.predict()`. No se agrega
  `torch.no_grad`/`inference_mode` explícito (sería redundante). El knob fp16 de YOLOE es el
  kwarg `half=True` de `.predict()`.
- **GDINO ya envuelve el forward en `torch.no_grad()`** (línea 100). Su palanca principal es
  fp16/autocast sobre el backbone visual, no el cache de texto.
- **Ambos adaptadores alimentan APIs de alto nivel** (`processor(...)` de HF,
  `model.predict(source=...)` de Ultralytics) que **re-preprocesan internamente**. Por eso no se
  usa `prepare_model_input` (tensor directo): requeriría bajar de nivel. Además el `forward()`
  pasa el payload **ya letterboxed** y la librería **vuelve a letterboxar** (doble preproceso).
- **Cache de embeddings de texto en GDINO:** descartado en este ciclo. Con prompt sets cortos
  (~4 prompts) el costo de tokenización es marginal frente al forward visual, y cachear los
  embeddings exigiría tocar internals del modelo HF (riesgo alto, payoff incierto).

## 4. WS1 — Inferencia

Principio: knobs donde corresponden (catálogo de modelo en `configs/models/<familia>/<variante>.yaml`),
default seguro, no-op sin CUDA, cada cambio validado contra el BENCH.

### 4.1 Grounding DINO (`grounding_dino_adapter.py`)

- **fp16/autocast:** envolver el forward (`self.model(**inputs)`) en
  `torch.autocast("cuda", dtype=torch.float16)` cuando `device` es CUDA y el flag está activo.
  No-op en CPU.
- **Warmup:** en `load()`, ejecutar una inferencia dummy (imagen negra del `target_size` del
  `input_spec` + prompts de calentamiento) para pagar JIT/init fuera del primer frame real.
- **Reducción de copia:** pasar el `np.ndarray` directo a `processor(images=...)` (acepta numpy)
  en lugar de `Image.fromarray(...)`. Validar que el resultado de detección no cambie.

### 4.2 YOLOE (`yoloe_adapter.py`)

- **fp16:** pasar `half=True` en `predict_kwargs` cuando `device` es CUDA y el flag está activo.
- **Validación de device:** en `load()`, normalizar/validar el device; si se pide CUDA y no está
  disponible, emitir warning y degradar a CPU (en vez de fallar silenciosamente).
- **Warmup:** inferencia dummy en `load()` análoga a GDINO.
- **Reducción de copia / doble letterbox:** evaluar pasar numpy directo a Ultralytics
  (acepta `np.ndarray`), cuidando la convención RGB/BGR, y evitar el doble letterbox. Cambio más
  sutil: se valida contra el BENCH antes de darlo por bueno; si introduce regresión, se revierte.
- **`no_grad` explícito:** NO se agrega (Ultralytics ya gestiona inference mode). Se documenta para
  que no reaparezca como pendiente.

### 4.3 Configuración

Nuevo bloque opcional en el schema de modelo (`config/schemas.py`, sección de modelo):

```yaml
# configs/models/<familia>/<variante>.yaml
runtime:
  half_precision: true   # fp16 cuando device=cuda; ignorado en cpu
  warmup: true           # inferencia dummy al cargar
```

Defaults: `half_precision: true`, `warmup: true`. El adaptador recibe estos valores en su
constructor (vía el factory `create_adapter()` en `models/__init__.py`).

**Reproducibilidad:** las corridas canónicas de BENCH deben fijar `half_precision` explícitamente,
porque fp16 mueve levemente los scores y puede mover el AP. Se documenta en
`docs/usage.md` / la sección de evaluación.

## 5. WS2 — Transporte (compresión JPEG)

Solo afecta el camino de red (dos nodos). El single-host (`memory.py`) pasa el `NormalizedUnit`
por referencia y **no se modifica**.

### 5.1 Wire format autodescriptivo

En `transport/serialization.py`, agregar el campo `payload_codec` al header msgpack:

- `serialize_unit(unit, codec="jpeg", quality=Q)`:
  - `payload_format == UINT8_RGB` y `codec == "jpeg"` → `cv2.imencode(".jpg", payload,
    [cv2.IMWRITE_JPEG_QUALITY, Q])`; `payload_codec = "jpeg"`.
  - `payload_format == FP32` (no comprimible) o `codec == "raw"` → comportamiento actual
    (`np.ascontiguousarray(payload).tobytes()`); `payload_codec = "raw"`. Si era FP32 con codec
    jpeg solicitado, warning de fallback.
- `deserialize_unit(data)`: lee `payload_codec` del header.
  - `"jpeg"` → `cv2.imdecode(...)` (recupera el array letterboxed del `target_size`).
  - `"raw"` → `np.frombuffer(...).reshape(target_size + (3,))` (actual).

El receptor no necesita configuración: el codec viaja en el header.

**Detalle a validar:** consistencia de canales RGB en el round-trip de `cv2`. encode/decode son
simétricos, así que no debería requerir swap; se cubre con un test de round-trip.

### 5.2 Configuración

Sección de transporte del run config:

```yaml
transport:
  compression:
    codec: jpeg     # jpeg | raw
    quality: 90     # 1-100, solo si codec=jpeg
```

Default: `codec: jpeg`, `quality: 90` para el transporte de red. El nodo productor pasa estos
valores a `serialize_unit`.

## 6. Medición (antes/después, sin infra nueva)

- **Inferencia:** corrida DBE single-host sobre la misma config antes y después; comparar
  `p50/p95/p99` y `fps_effective` de `summary.json`. El warmup debe reflejarse en la caída del p99.
- **Transporte:** corrida dos-nodos antes y después; latencia/FPS vía `summary.json`. Reducción de
  ancho de banda verificada con un log `debug` del tamaño del mensaje serializado (una línea; no
  contamina las métricas del pipeline).

## 7. Testing

- **Round-trip de serialización** (`tests/test_serialization.py`):
  - `codec="jpeg"` → `serialize_unit` → `deserialize_unit` preserva shape y dtype y el contenido
    dentro de un umbral (PSNR o diff acotado).
  - `codec="raw"` → round-trip exacto (comportamiento actual).
  - `payload_format == FP32` con codec jpeg → fallback a raw + warning.
- **fp16 / warmup:**
  - En CPU (CI) `half_precision` es no-op → test de la ruta de degradación.
  - `load()` con `warmup: true` ejecuta la inferencia dummy sin error.
  - device CUDA solicitado sin GPU → warning + degradación a CPU (YOLOE).
- **Regresión:** toda la suite vigente debe seguir verde.
- **Precisión:** validación manual contra el BENCH (single-host, fp16 fijado) para confirmar que
  los cambios de inferencia no degradan el AP de forma significativa.

## 8. Riesgos

1. **fp16 mueve scores → puede mover el AP del BENCH.** Mitigación: configurable + documentar que
   las corridas canónicas fijen `half_precision`. La eval reproducible corre single-host (raw).
2. **JPEG es lossy.** Degradación mínima a q90, pero existe. Solo afecta el camino de red/live,
   nunca la eval reproducible (single-host = raw). `quality` configurable y `raw` como escape.
3. **Doble letterbox / reducción de copias (YOLOE/GDINO):** el cambio más sutil; se valida contra
   el BENCH y se revierte si introduce regresión de precisión.

## 9. Criterio de cierre

- fp16 y warmup activos y configurables en GDINO y YOLOE, no-op sin CUDA.
- Compresión JPEG autodescriptiva en el transporte de red, con fallback raw para FP32.
- Suite de tests verde; nuevos tests de round-trip JPEG y de degradación fp16/warmup.
- Mejora medible en `p50/p95/p99`/`fps_effective` documentada antes/después.
- Sin regresión de AP en el BENCH (validación manual con fp16 fijado).
