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
    └── experiments/   # matriz experimental (ver docs/experimentos/)
```

## Anatomía de una run config

```yaml
run:
  name: p_e1b_yoloe_short_15
  description: "..."

source:
  ref: dataset_v1              # → configs/datasets/dataset_v1.yaml

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
(`*_v2_short`), nunca editar uno ya usado por experimentos.

## Validar y ejecutar

```bash
eovrt-media validate-config --config configs/runs/<archivo>.yaml
eovrt-media run --config configs/runs/<archivo>.yaml
```
