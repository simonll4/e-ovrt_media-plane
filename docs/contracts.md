# Contratos de Datos

Este documento describe los contratos Pydantic del plano de medios.

## VisualUnit

Representa una imagen o frame procesable.

| Campo            | Tipo            | Descripción                                |
|------------------|-----------------|--------------------------------------------|
| `unit_id`        | `str`           | Identificador único de la unidad           |
| `source_path`    | `str`           | Ruta de la fuente original                 |
| `source_type`    | `str`           | Tipo: `image`, `video_frame`               |
| `frame_index`    | `int \| None`   | Índice del frame (None para imágenes)      |
| `width`          | `int`           | Ancho en píxeles                           |
| `height`         | `int`           | Alto en píxeles                            |
| `timestamp_ms`   | `float \| None` | Timestamp del frame en ms (None para img)  |

## Detection

Representa una detección normalizada.

| Campo              | Tipo           | Descripción                              |
|--------------------|----------------|------------------------------------------|
| `label`            | `str`          | Label devuelto por el modelo             |
| `prompt_id`        | `str \| None`  | ID del prompt mapeado (de YAML)          |
| `confidence`       | `float`        | Confianza [0, 1]                         |
| `bbox_xyxy`        | `list[float]`  | Bounding box en píxeles [x1, y1, x2, y2]|
| `bbox_norm_xyxy`   | `list[float]`  | Bounding box normalizado [0, 1]          |
| `model_name`       | `str`          | Nombre del adaptador de modelo           |

## DetectionEvent

Evento principal del plano de medios, agrupando todas las detecciones de una unidad visual.

| Campo            | Tipo                    | Descripción                           |
|------------------|-------------------------|---------------------------------------|
| `run_id`         | `str`                   | ID de la corrida                      |
| `unit_id`        | `str`                   | ID de la unidad visual procesada      |
| `source_path`    | `str`                   | Ruta de la fuente                     |
| `model_adapter`  | `str`                   | Nombre del adaptador utilizado        |
| `prompt_version` | `str`                   | Versión de los prompts                |
| `detections`     | `list[Detection]`       | Lista de detecciones                  |
| `timing_ms`      | `dict[str, float]`      | Tiempos: `total`, `inference`         |

## RunSummary

Resumen de una corrida completa.

| Campo              | Tipo    | Descripción                            |
|--------------------|---------|----------------------------------------|
| `run_id`           | `str`   | ID de la corrida                       |
| `scenario`         | `str`   | Escenario: `DBE`                       |
| `model_adapter`    | `str`   | Nombre del adaptador                   |
| `source_count`     | `int`   | Cantidad de fuentes encontradas        |
| `units_processed`  | `int`   | Unidades procesadas exitosamente       |
| `units_failed`     | `int`   | Unidades con error                     |
| `total_detections` | `int`   | Total de detecciones en la corrida     |
| `avg_latency_ms`   | `float` | Latencia promedio por unidad           |
| `p50_latency_ms`   | `float` | Percentil 50 de latencia              |
| `p95_latency_ms`   | `float` | Percentil 95 de latencia              |
| `started_at`       | `str`   | Timestamp de inicio ISO 8601           |
| `finished_at`      | `str`   | Timestamp de fin ISO 8601              |

## Convención de bounding boxes

- `bbox_xyxy`: siempre en píxeles `[x1, y1, x2, y2]`.
- `bbox_norm_xyxy`: siempre normalizado entre 0 y 1.
- `confidence`: siempre entre 0 y 1.
