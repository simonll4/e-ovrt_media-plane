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
| `yoloe/original/mobileclip2_b.ts` | 242 MB | [Ultralytics assets v8.4.0](https://github.com/ultralytics/assets/releases/download/v8.4.0/mobileclip2_b.ts) | AGPL-3.0 |
| `yoloe/original/yolo26n.pt` | 5 MB | [Ultralytics assets v8.4.0](https://github.com/ultralytics/assets/releases/download/v8.4.0/yolo26n.pt) | AGPL-3.0 |
| `grounding-dino/original/grounding-dino-tiny/` | 689 MB | [HF: IDEA-Research/grounding-dino-tiny](https://huggingface.co/IDEA-Research/grounding-dino-tiny), revisión `a2bb814dd30d776dcf7e30523b00659f4f141c71` | Apache-2.0 |
| `grounding-dino/original/grounding-dino-base/` | 933 MB | [HF: IDEA-Research/grounding-dino-base](https://huggingface.co/IDEA-Research/grounding-dino-base), revisión `12bdfa3120f3e7ec7b434d90674b3396eccf88eb` | Apache-2.0 |
| `edge/person-detection-retail-0013_6shave.blob` | 2 MB | Open Model Zoo, compilado con `blobconverter` (`make download-prefilter-blob`) | Apache-2.0 |
| `yoloe/finetuned/t1/best.pt`, `t2/best.pt` | 20 / 28 MB | checkpoints propios (jobs 1167640 y 1167982 del clúster): `4-fine-tuning/checkpoints.zip` del paquete de evidencia, `finetuned/full-<job>/weights/best.pt` | — |

**Versiones fijadas (✎ 2026-10-27).** `download_models.sh` baja cada peso en la versión exacta con
que se midió: la revisión del Hub de cada Grounding DINO y el release `v8.4.0` de
`ultralytics/assets` (YOLOE-26, `mobileclip2_b.ts`, `yolo26n.pt`). Verificado el 2026-10-27: las
dos revisiones del Hub son las que tenía `main`; el digest sha256 que publica GitHub para los seis
assets de YOLOE coincide con los pesos en uso; y `blobconverter` vuelve a compilar el blob de la
OAK-D idéntico byte a byte. Los checkpoints del ajuste fino no se descargan de ningún lado: se
copian del paquete de evidencia (job 1167640 → `t1/`, job 1167982 → `t2/`).

**Cabeza de cajas de `grounding-dino-base` (✎ 2026-10-30).** El checkpoint del Hub guarda la cabeza compartida del
decoder como `model.decoder.bbox_embed.0.*`; `transformers==5.12.1` (fijado en `constraints.txt`) no mapea ese
nombre y la deja en valores de inicialización sin avisar (`missing_keys` vacío), así que el decoder no refina las
cajas. El adaptador la restaura al cargar (`restore_decoder_bbox_head`, con aviso en el log). `tiny` guarda la
cabeza como `bbox_embed.0.*` y no pasa por ahí. Si `sha256sum -c` de la lista de huellas dice que el
`model.safetensors` de base no coincide, volver a bajarlo con `make download-models`: un archivo guardado con
`save_pretrained` desde una carga rota conserva la cabeza sin entrenar.
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
  prompts de YOLOE. ✎ 2026-10-27: **lo descarga `download_models.sh`** (es un
  release asset de `ultralytics/assets` v8.4.0; la nota anterior decía que no lo
  era). El compose de `infra/` lo monta desde ahí como cache
  (`/app/mobileclip2_b.ts`) para que el contenedor no lo re-descargue: **si el
  archivo no existe en el host, Docker crea una carpeta vacía con ese nombre** y
  YOLOE falla al cargar. Bajarlo antes del primer `up` de una instancia YOLOE.
