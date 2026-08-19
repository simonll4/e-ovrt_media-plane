# configs/_archive

Configuraciones archivadas el **2026-08-19** (pase de limpieza). Se conservan como
constancia histórica; **nada en `src/` ni en `tests/` las referencia** (verificado en
la auditoría previa al archivado). Convención `_archive` espejo de la usada en el
repo hermano `e-ovrt_control-plane`.

## Contenido

- **`chv.yaml`** — entrada de catálogo de dataset para CHV. Huérfana: cero
  referencias en código, tests o docs; superada por las entradas
  `bench_v2_test.yaml` / `bench_v2_val.yaml` / `demo_v2.yaml` del catálogo vigente.
- **`video_sample.yaml`** — config de corrida de video de muestra. Su único
  referente (`data/samples/videos/README.md`) apuntaba a una config que ya no
  existía en `configs/runs/`; el camino vigente para correr video es
  `POST /api/runs` con `ingest.plugin: video_file`.
- **`mm-grounding-dino/`** (`mm-gdino-tiny.yaml`, `mm-gdino-base.yaml`,
  `mm-gdino-large.yaml`) — familia de catálogos MM-Grounding-DINO. Nunca fueron
  ejercitadas por ninguna corrida ni test; marcadas como no usadas desde la
  auditoría M10 (2026-06-25). MM-GDINO-tiny fue descartado en el Sprint 2 por
  bounding boxes rotos. Los pesos ya no se descargan con
  `scripts/download_models.sh` (los que estén en disco bajo
  `models/mm-grounding-dino/` quedan a criterio del usuario).
