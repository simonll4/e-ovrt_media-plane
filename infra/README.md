# Infra — servicio media-plane (deploy standalone)

Imagen y compose para desplegar **solo este servicio** (una instancia). La plataforma
completa (consola + fleet de modelos) vive en `e-ovrt_experimental-setup/infra/platform/`.

## Build + run

```bash
cd infra
docker compose build                                  # imagen eovrt/media-plane:latest
EOVRT_MODEL_REF=mock docker compose up -d             # o grounding-dino/gdino-tiny, yoloe/yoloe-26s, ...
curl -s http://localhost:8080/readyz                  # {"status":"ready","model":"..."}
```

Requisitos: pesos descargados en `../models/` (`make download-models`), repo
`e-ovrt_datasets` como hermano (para datasets/GT del BENCH), y para modelos GPU el
runtime NVIDIA (`nvidia-container-toolkit`). En host sin GPU, comentar el bloque
`deploy.resources` (solo `mock` tiene sentido ahí; `device: auto` cae a cpu solo).

**Text-encoder de YOLOE**: `models/yoloe/original/mobileclip2_b.ts` **no lo
descarga** `download_models.sh` (no es un release asset de Ultralytics); la
librería lo baja sola en la primera corrida YOLOE con prompts de texto, y hay
que colocarlo manualmente en `models/yoloe/original/`. El compose lo monta
desde ahí como cache (`/app/mobileclip2_b.ts:ro`) para que el contenedor no
intente re-descargarlo. Si falta el archivo, comentar ese volumen (con modelos
GDINO/mock no se usa).

## Smoke

```bash
curl -s -X POST http://localhost:8080/api/runs -H 'Content-Type: application/json' -d '{
  "ingest": {"plugin": "image_folder", "config": {"dataset": "demo_v2"}},
  "prompts": {"set_inline": {"id": "smoke", "classes": [{"id": "person", "phrasings": {"default": ["person"]}}]},
               "active_ids": null},
  "run": {"max_units": 3}
}'
# esperar succeeded:
curl -s http://localhost:8080/api/runs/<run_id>
```

Cambiar de modelo = `docker compose down` + `up` con otro `EOVRT_MODEL_REF` (sin
recarga in-process, por diseño del Spec A).
