# Configs

Toda la variación del pipeline vive acá, organizada en **catálogos** (qué
existe) y **runs** (qué se ejecuta). Una run config compone entradas de los
catálogos por referencia y solo declara lo que cambia.

```
configs/
├── models/      # catálogo de modelos: un YAML por variante de pesos
│   ├── mock.yaml
│   ├── yoloe/yoloe-26s.yaml
│   └── grounding-dino/{gdino-tiny,gdino-base}.yaml
├── datasets/    # catálogo de fuentes: imágenes o video
├── prompts/     # catálogo de prompt sets versionados
└── runs/        # configs ejecutables (componen los catálogos de arriba)
```

## Anatomía de una run config

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
  ref: cr01_cr02_v2_short      # → configs/prompts/cr01_cr02_v2_short.yaml
  active_ids: [person, helmet, vest]

postprocess:                   # secciones opcionales: defaults razonables
  min_confidence: 0.15
```

Reglas de resolución:

- `ref` se resuelve contra esta carpeta (`configs/`); los campos inline de la
  run config **pisan** los del catálogo.
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
  payload_format: uint8_rgb # uint8_rgb/fp32 implementados; fp16 pendiente

topology:
  mode: single_host         # single_host y two_node implementados
```

Los defaults se derivan antes de validar: una fuente `pulleable` usa
`deterministic`, una `live` usa `bounded_freshness`; `single_host` usa `memory`
y `two_node` usa `network`.

Los valores declarados pero no disponibles (`oak_d`, `fp16`) fallan de forma
explícita al cargar la config. Las entradas de `datasets/`
incluyen `dataset_id`, `view`, `split`, `vocabulary` y `kind`; esos campos se
persisten en `run_provenance.json`.

## Catálogos

**`models/<familia>/<variante>.yaml`** — describe un peso concreto: `family`,
`variant`, `lineage` (`original` | `finetuned`), `adapter`, ruta de pesos y
umbrales por defecto. Los pesos en sí viven en
`models/<familia>/{original,finetuned/<tag>}/` (ver `models/README.md`).
Convención de nombre para finetunes: `<variante>-ft-<tag>.yaml`.

**`datasets/<nombre>.yaml`** — una fuente de datos: `type`
(`image_folder` | `video_file`), `path` y opcionales.

**`prompts/<nombre>.yaml`** — un `prompt_set` versionado con `id`, `items`
(id, texto, aliases, rol). Versionar cambios de vocabulario como un set nuevo
(`*_v2`), nunca editar un set ya usado por una corrida registrada.

## Validar y ejecutar

```bash
eovrt-media validate-config --config configs/runs/<archivo>.yaml
eovrt-media run --config configs/runs/<archivo>.yaml
```
