# Models

Este directorio contiene los **pesos** de los modelos. El **catálogo** que los
describe (adapter, rutas, umbrales por defecto) vive en `configs/models/` —
las configs de run referencian entradas del catálogo, nunca rutas de pesos
directamente.

## Estructura

```
models/
├── grounding-dino/
│   ├── original/
│   │   ├── grounding-dino-tiny/    # IDEA-Research/grounding-dino-tiny
│   │   └── grounding-dino-base/    # IDEA-Research/grounding-dino-base
│   └── finetuned/                  # un subdirectorio por finetune: <tag>/
├── mm-grounding-dino/              # ARCHIVADO 2026-08-19 — ver nota más abajo
│   ├── original/
│   │   ├── mm_grounding_dino_tiny_o365v1_goldg_v3det/
│   │   ├── mm_grounding_dino_base_all/
│   │   └── mm_grounding_dino_large_all/
│   └── finetuned/
└── yoloe/
    ├── original/
    │   ├── yoloe-26s-seg.pt        # YOLOE small segmentation
    │   ├── yoloe-26m-seg.pt        # YOLOE medium segmentation
    │   ├── yoloe-26l-seg.pt        # YOLOE large segmentation
    │   └── yoloe-26x-seg.pt        # YOLOE xlarge segmentation
    └── finetuned/                  # un subdirectorio por finetune: <tag>/
```

## Origen de cada checkpoint

Pesos originales descargados de fuentes oficiales (la misma información vive
en el campo `source` de cada entrada de `configs/models/`):

| Checkpoint | Tamaño | Fuente oficial | Licencia |
| --- | --- | --- | --- |
| `yoloe/original/yoloe-26s-seg.pt` | 30 MB | [Ultralytics assets v8.4.0](https://github.com/ultralytics/assets/releases/download/v8.4.0/yoloe-26s-seg.pt) | AGPL-3.0 |
| `yoloe/original/yoloe-26m-seg.pt` | 68 MB | [Ultralytics assets v8.4.0](https://github.com/ultralytics/assets/releases/download/v8.4.0/yoloe-26m-seg.pt) | AGPL-3.0 |
| `yoloe/original/yoloe-26l-seg.pt` | 76 MB | [Ultralytics assets v8.4.0](https://github.com/ultralytics/assets/releases/download/v8.4.0/yoloe-26l-seg.pt) | AGPL-3.0 |
| `yoloe/original/yoloe-26x-seg.pt` | 164 MB | [Ultralytics assets v8.4.0](https://github.com/ultralytics/assets/releases/download/v8.4.0/yoloe-26x-seg.pt) | AGPL-3.0 |
| `grounding-dino/original/grounding-dino-tiny/` | 689 MB | [HF: IDEA-Research/grounding-dino-tiny](https://huggingface.co/IDEA-Research/grounding-dino-tiny) | Apache-2.0 |
| `grounding-dino/original/grounding-dino-base/` | 929 MB | [HF: IDEA-Research/grounding-dino-base](https://huggingface.co/IDEA-Research/grounding-dino-base) | Apache-2.0 |
| `mm-grounding-dino/original/mm_grounding_dino_tiny_o365v1_goldg_v3det/` (archivado) | 692 MB | [HF: openmmlab-community](https://huggingface.co/openmmlab-community/mm_grounding_dino_tiny_o365v1_goldg_v3det) | Apache-2.0 |
| `mm-grounding-dino/original/mm_grounding_dino_base_all/` (archivado) | 936 MB | [HF: openmmlab-community](https://huggingface.co/openmmlab-community/mm_grounding_dino_base_all) | Apache-2.0 |
| `mm-grounding-dino/original/mm_grounding_dino_large_all/` (archivado) | 1376 MB | [HF: openmmlab-community](https://huggingface.co/openmmlab-community/mm_grounding_dino_large_all) | Apache-2.0 |

Documentación de referencia: [Ultralytics YOLOE](https://docs.ultralytics.com/models/yoloe/)
y [Transformers Grounding DINO](https://huggingface.co/docs/transformers/model_doc/grounding-dino).

**Sobre MM-Grounding-DINO — familia ARCHIVADA (2026-08-19)**: son
re-entrenamientos abiertos de la arquitectura Grounding DINO publicados por
OpenMMLab (proyecto
[MMDetection](https://github.com/open-mmlab/mmdetection/tree/main/configs/mm_grounding_dino),
conversión oficial a transformers en la org `openmmlab-community` del Hub);
usaban el mismo adapter `grounding_dino` (transformers >= 4.50, model_type
`mm-grounding-dino`). Sus catálogos fueron archivados en
`configs/_archive/mm-grounding-dino/` y `scripts/download_models.sh` **ya no
descarga sus pesos**. Resultado histórico: MM-GDINO-tiny fue **descartado en el
Sprint 2 por bounding boxes rotos**; ninguna variante de la familia fue
ejercitada por corridas ni tests desde entonces. Los pesos que queden en disco
bajo `models/mm-grounding-dino/` son un remanente local.

**Finetunes EPP de terceros**: a la fecha (2026-06) no hay finetunes públicos
de Grounding DINO para EPP/PPE en HF Hub (búsquedas "grounding dino ppe/safety/
helmet" sin resultados verificables). Si aparecen, catalogarlos bajo
`finetuned/<tag>/` previa verificación de licencia y calidad.

Las variantes prompt-free de YOLOE (`yoloe-26*-seg-pf.pt`) existen en la misma
fuente de Ultralytics pero no se descargan: el proyecto prioriza evaluación
open-vocabulary guiada por prompts.

Convención por familia de modelo:

- `original/` — pesos publicados por el proveedor, sin modificar.
- `finetuned/<tag>/` — checkpoints propios. El `<tag>` identifica el
  entrenamiento (p. ej. `mocs-epp-v1`) y debe coincidir con el nombre de su
  entrada en el catálogo: `configs/models/<familia>/<variante>-ft-<tag>.yaml`.

## Alta de un peso nuevo

1. Copiar los pesos a `models/<familia>/{original|finetuned/<tag>}/`.
2. Crear su entrada de catálogo en `configs/models/<familia>/<nombre>.yaml`
   (ver ejemplos existentes: `family`, `variant`, `lineage`, `adapter`,
   ruta de pesos y umbrales por defecto).
3. Referenciarlo desde una run config con `model.ref: <familia>/<nombre>`.

## Descarga

```bash
make download-models
# o directamente:
./scripts/download_models.sh
```

## Notas

- Los pesos **no se versionan** en Git (ver `.gitignore`); solo se versionan
  los archivos de configuración livianos (tokenizer, config.json, etc.).
- **`models/yoloe/original/mobileclip2_b.ts`** es el encoder de texto de los
  prompts de YOLOE. **No lo descarga `download_models.sh`** (no es un release
  asset descargable de Ultralytics): la librería lo baja sola al CWD en la
  primera corrida YOLOE con prompts de texto, y hay que **colocarlo manualmente**
  en `models/yoloe/original/` para conservarlo con el resto de los pesos. El
  compose de `infra/` lo monta desde ahí como cache (`/app/mobileclip2_b.ts`)
  para que el contenedor no lo re-descargue.
