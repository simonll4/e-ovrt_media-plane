# Diseño: validación RTSP EZVIZ con YOLOE en un solo host

## Objetivo

Validar de punta a punta una cámara EZVIZ en la LAN mediante RTSP y detección real
con YOLOE-26s en la GPU local, produciendo artefactos de corrida que permitan evaluar
conectividad, estabilidad, latencia, consumo de VRAM y detecciones de EPP.

## Decisión

Se ejecutará la topología `single_host`. La misma PC dispone de una NVIDIA GeForce
RTX 4060 Laptop GPU con 8 GB de VRAM, CUDA disponible en PyTorch, y pesos locales de
YOLOE-26s. La topología de dos nodos y Docker quedan fuera de esta prueba inicial:
no reducen el riesgo de conexión RTSP y añaden la limitación conocida del `input_spec`
en el nodo edge.

La prueba usará `YOLOE-26s`, `device: cuda:0`, `image_size: 640` y los prompts
`person`, `safety helmet` y `high visibility safety vest`. El flujo será:

```
EZVIZ RTSP -> RtspSource -> bounded_freshness (buffer 2) -> YOLOE-26s GPU
          -> JSONL de detecciones y métricas -> summary.json
```

## Configuración local y secretos

La URI RTSP provista es un secreto de prueba. No se incluirá en documentación,
configuraciones versionadas, commits ni salidas de terminal. La configuración operativa
vivirá en `configs/runs/local/ezviz_yoloe_rtsp.yaml`, directorio ignorado por Git.

El YAML local será una configuración completa basada en los catálogos existentes:

```yaml
run:
  scenario: EBE
  name: ezviz_yoloe_rtsp
  max_units: 120

source:
  type: rtsp
  path: "<RTSP_URI_LOCAL>"
  url: "<RTSP_URI_LOCAL>"
  reconnect_retries: 5
  reconnect_delay_ms: 1000

model:
  ref: yoloe/yoloe-26s
  device: cuda:0

prompts:
  ref: cr01_cr02_v1
  active_ids: [person, helmet, vest]

rate_control:
  policy: bounded_freshness
  buffer_size: 2
  max_staleness_ms: 1000

topology:
  mode: single_host

transport:
  backend: memory
  payload_format: uint8_rgb

outputs:
  run_dir: runs
  base_dir: runs
  save_previews: false
```

Los artefactos de `runs/` ya están ignorados. Como el pipeline persiste la configuración
efectiva y el `source_path`, la URI estará presente dentro del directorio local de la
corrida; ese directorio no debe compartirse sin sanearlo.

## Secuencia de validación

1. **Preflight local:** confirmar CUDA, VRAM libre, import de Ultralytics y existencia del
   peso `models/yoloe/original/yoloe-26s-seg.pt`.
2. **Sonda RTSP aislada:** abrir la URI con OpenCV, leer al menos 30 frames consecutivos y
   registrar resolución, frames leídos y duración. El diagnóstico informa sólo host y puerto,
   nunca la URI completa.
3. **Corrida corta:** ejecutar 120 unidades con el YAML local. Debe terminar sin errores de
   fuente ni inferencia y generar `detections.jsonl`, `metrics.jsonl`, `errors.jsonl`,
   `summary.json`, `effective_config.yaml` y `run_manifest.json`.
4. **Evaluación:** comprobar que `units_processed > 0`, `units_failed == 0`,
   `gpu_memory_peak_mb > 0`, y que las muestras de `metrics.jsonl` tengan `device: cuda:0`.
   Revisar detecciones y las latencias p50/p95 antes de cambiar parámetros.
5. **Corrida sostenida:** sólo si la corrida corta cumple los criterios, aumentar
   `run.max_units` para cubrir al menos cinco minutos al FPS efectivo observado. Mantener
   `bounded_freshness`; el objetivo es privilegiar frames recientes sobre cobertura total.

## Criterios de aceptación

- RTSP abre y entrega al menos 30 frames consecutivos durante la sonda.
- La corrida corta completa las 120 unidades sin `ConnectionError` ni eventos de error.
- YOLOE usa `cuda:0` y registra memoria GPU mayor que cero.
- `summary.json` declara topología `single_host`, backend `memory`, política
  `bounded_freshness` y fuente de tipo `rtsp`.
- Si aparecen errores o la latencia p95 impide la tasa observada, el siguiente ajuste se
  decide a partir de `metrics.jsonl`: bajar `image_size`, reducir prompts activos, o aumentar
  `buffer_size`; no se cambia más de un parámetro por corrida.

## Fuera de alcance

- Despliegue Docker y topología de dos nodos.
- Persistencia de previews anotadas: el pipeline actual no renderiza previews de `video_frame`.
- Interpolación de variables de entorno para YAML; la configuración sensible es local e ignorada.
