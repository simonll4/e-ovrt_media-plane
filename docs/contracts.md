# Contratos de datos

Los contratos del plano de medios separan ingesta, payload normalizado, inferencia y
artefactos. Se implementan con Pydantic v2 salvo `ResizeTransform`, que es una dataclass.

## Flujo de contratos

```
VisualUnit → NormalizedUnit → RawDetection[] → Detection[] → DetectionEvent
```

`VisualUnit` describe la fuente. `NormalizedUnit` es la unidad que cruza el canal entre
productor y consumidor. Las cajas crudas están en el espacio del modelo y se reproyectan
al tamaño original antes de persistirse como `Detection`.

## `VisualUnit`

| Campo | Tipo | Descripción |
|---|---|---|
| `run_id` | `str \| None` | Corrida propietaria, si ya fue asignada. |
| `unit_id` | `str` | Identificador único de imagen o frame. |
| `source_id` | `str \| None` | Identificador legible de fuente. |
| `source_type` | `str` | `image` o `video_frame`. |
| `frame_index` | `int \| None` | Índice original de frame. |
| `timestamp_ms` | `float \| None` | Timestamp de la unidad. |
| `width`, `height` | `int` | Dimensiones originales. |
| `path` / `source_path` | `str \| None` | Ruta de la fuente; se mantienen sincronizadas. |

## `NormalizedUnit` y transformación espacial

| Campo | Tipo | Descripción |
|---|---|---|
| Metadata | campos de `VisualUnit` | Identidad y referencia temporal conservadas. |
| `orig_width`, `orig_height` | `int` | Tamaño antes del resize. |
| `payload` | `numpy.ndarray` | Píxeles RGB normalizados espacialmente. |
| `payload_format` | `uint8_rgb \| fp32 \| fp16` | Los tres formatos están implementados; FP16 se normaliza a `[0, 1]` y conserva `float16` en el wire raw. |
| `target_size` | `tuple[int, int]` | Alto y ancho del payload. |
| `transform` | `ResizeTransform` | Escalas y padding para volver del espacio modelo al original. |

`ResizeTransform.project_to_original()` aplica la inversa de resize/letterbox a una caja
`[x1, y1, x2, y2]`. `END` es el centinela de cierre del canal.

## Canal de transporte

```python
class TransportAdapter:
    def offer(self, unit: NormalizedUnit) -> None: ...
    def request(self, **kwargs) -> NormalizedUnit | type[END]: ...
    def close(self) -> None: ...
```

Los backends `memory` y `network` implementan esta interfaz. En red, los datos usan
ZeroMQ REQ/REP y la liveness usa un canal PUSH/PULL dedicado. El wire raw soporta
`uint8_rgb`, `fp32` y `fp16`; JPEG sólo codifica payloads `uint8_rgb`.

## Detecciones y eventos

`RawDetection` contiene la respuesta del adaptador. `DetectionNormalizer` filtra confianza y
área, reproyecta con `ResizeTransform`, calcula `bbox_norm_xyxy` y asigna `prompt_id`.

`DetectionEvent` versión `media.detection.v1` persiste una unidad procesada con bloques
estructurados `source`, `model`, `prompts`, `detections` y `timing`.

## Métricas, resumen y procedencia

| Contrato / archivo | Versión | Contenido relevante |
|---|---|---|
| `MetricSample` / `metrics.jsonl` | `media.metric.v2` | Latencia total, de inferencia y de normalización; FPS, detecciones y memoria GPU. |
| `RunSummary` / `summary.json` | `media.summary.v2` | Conteos, avg/p50/p95/p99, FPS, descartes, backpressure y `run_descriptor`. |
| `RunDescriptor` | embebido | Escenario, topología, transporte, rate control, fuente, modelo, prompts, dispositivo y versión de código. |
| `run_provenance.json` | JSON | Dataset, vista, split, vocabulario y fingerprint SHA-256 de la fuente. |

El fingerprint se calcula sobre el listado ordenado de archivos directos de la fuente, usando
nombre y tamaño. Es coherente con `ImageFolderSource`, que no recorre subdirectorios.

## Convenciones de bounding boxes

- `bbox_xyxy`: píxeles originales, `[x1, y1, x2, y2]`.
- `bbox_norm_xyxy`: mismas coordenadas normalizadas a `[0, 1]`.
- `confidence`: valor entre 0 y 1.
