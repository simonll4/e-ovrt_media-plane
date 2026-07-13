# Configs

Acá viven los **catálogos de capacidades** del plano (qué modelos y fuentes
existen). Los **manifiestos de corrida** (qué se ejecuta) y los **prompt sets**
NO viven acá: residen en el repo hermano `e-ovrt_experimental-setup` y llegan al
plano vía la API del servicio (`POST /api/runs`). Un request compone entradas de
estos catálogos por referencia y solo declara lo que cambia.

```
configs/
├── models/      # catálogo de modelos: un YAML por variante de pesos
│   ├── mock.yaml
│   ├── yoloe/yoloe-26s.yaml
│   └── grounding-dino/{gdino-tiny,gdino-base}.yaml
└── datasets/    # catálogo de fuentes: imágenes o video
```

## Anatomía de un request de corrida

```yaml
run:
  scenario: DBE
  name: dbe_mock

source:
  ref: demo_v2                 # → configs/datasets/demo_v2.yaml

model:
  ref: yoloe/yoloe-26s         # → configs/models/yoloe/yoloe-26s.yaml
  device: cuda                 # override puntual sobre el catálogo
  confidence_threshold: 0.15

prompts:
  ref: cr01_cr02_v2_short      # → e-ovrt_experimental-setup/prompts/cr01_cr02_v2_short.yaml
  # o inline, sin repo hermano:
  # set_inline: {person: person, helmet: helmet, vest: vest}
  active_ids: [person, helmet, vest]

postprocess:                   # secciones opcionales: defaults razonables
  min_confidence: 0.15
```

Reglas de resolución:

- `model.ref`/`source.ref` se resuelven contra esta carpeta (`configs/`);
  `prompts.ref` se resuelve contra el repo hermano `e-ovrt_experimental-setup`
  (o se declara inline vía `prompts.set_inline`). Los campos inline del request
  **pisan** los del catálogo.
- Secciones omitidas (`rate_control`, `transport`, `topology`, `postprocess`, `outputs`, `logging`) toman
  los defaults definidos en `src/eovrt_media/config/schemas.py`.
- `sampling` ya no es válido: usar `rate_control.stride` y `run.max_units`.
- El formato inline completo (sin refs) sigue siendo válido; la config
  efectiva resuelta queda registrada en el manifest de cada run.

## Configuración de despliegue

```yaml
run:
  scenario: DBE
  max_units: null

rate_control:
  policy: deterministic     # deterministic | bounded_freshness
  stride: 1                 # solo deterministic
  max_queue_size: 8         # solo deterministic

transport:
  backend: memory           # memory y network (ZeroMQ) implementados
  payload_format: uint8_rgb # uint8_rgb, fp32 y fp16 implementados

  # Campos requeridos cuando backend=network (dos nodos):
  # endpoint: "tcp://0.0.0.0:5555"          # bind del productor / connect del consumidor
  # heartbeat_endpoint: "tcp://0.0.0.0:5556" # canal PUSH/PULL de liveness (obligatorio)
  # heartbeat_interval_ms: 1000              # cadencia de pulso del consumidor (ms)
  # heartbeat_timeout_ms: 5000              # umbral de liveness del productor (ms)
  # compression:
  #   codec: jpeg   # jpeg | raw (jpeg solo para payload_format=uint8_rgb)
  #   quality: 90   # calidad JPEG 1-100

topology:
  mode: single_host         # single_host y two_node implementados
```

Los defaults se derivan antes de validar: una fuente `pulleable` usa
`deterministic`, una `live` usa `bounded_freshness`; `single_host` usa `memory`
y `two_node` usa `network`.

Las cuatro fuentes declaradas están implementadas (`oak_d` desde 2026-07-13;
requiere el SDK DepthAI del extra `edge`). Las entradas de `datasets/`
incluyen `dataset_id`, `view`, `split`, `vocabulary` y `kind`; esos campos se
persisten en `run_provenance.json`.

## Catálogos

**`models/<familia>/<variante>.yaml`** — describe un peso concreto: `family`,
`variant`, `lineage` (`original` | `finetuned`), `adapter`, ruta de pesos y
umbrales por defecto. Los pesos en sí viven en
`models/<familia>/{original,finetuned/<tag>}/` (ver `models/README.md`).
Convención de nombre para finetunes: `<variante>-ft-<tag>.yaml`.

**`datasets/<nombre>.yaml`** — una fuente de datos: `type`
(`image_folder` | `video_file` | `rtsp` | `oak_d`), `path` y opcionales.
`rtsp` y `oak_d` están implementados (fuentes live, política `bounded_freshness`);
`oak_d` requiere `url` = IP fija de la cámara y admite `resolution`/`fps`/`orientation`
(ver docs/contexto/oak-d-integration.md).

Los **prompt sets** versionados (`id`, `items`, aliases, rol) NO son un catálogo
del plano: viven en `e-ovrt_experimental-setup/prompts/<nombre>.yaml` y se
referencian por `prompts.ref`, o se declaran inline en el request con
`prompts.set_inline`. Versionar cambios de vocabulario como un set nuevo (`*_v2`),
nunca editar un set ya usado por una corrida registrada.

## Ejecutar una corrida

Los manifiestos de corrida viven en `e-ovrt_experimental-setup`; el servicio los
recibe como request:

```bash
curl -X POST http://localhost:8080/api/runs \
  -H "Content-Type: application/json" \
  -d @<request>.json
```
