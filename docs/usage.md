# Uso del Plano de Medios

> **Nota (Fase 1):** el media-plane ya **no es un CLI**. El comando `eovrt-media`
> fue eliminado (Task 17); el pipeline se dispara como un **servicio HTTP/WS** que
> mantiene un único run activo. Los utilitarios ex-subcomandos ahora se invocan
> como módulos (`python -m eovrt_media.tools.*`).

## Instalación

```bash
# Clonar repositorio
git clone <url> eovrt-media-plane
cd eovrt-media-plane

# Crear entorno virtual
python3.11 -m venv .venv
source .venv/bin/activate

# Instalar
pip install --upgrade pip setuptools wheel
pip install -e ".[dev]"
```

O usar el script de bootstrap:

```bash
./scripts/bootstrap.sh
```

## Descarga de modelos

```bash
make download-models
```

Esto descarga la matriz completa de pesos originales:
1. **Grounding DINO tiny y base** desde Hugging Face → `models/grounding-dino/original/`
2. **MM-Grounding-DINO tiny/base/large** (OpenMMLab) desde Hugging Face → `models/mm-grounding-dino/original/`
3. **YOLOE-26 s/m/l/x** desde Ultralytics release assets → `models/yoloe/original/`

La fuente oficial y licencia de cada checkpoint están documentadas en la tabla
de `models/README.md` y en el campo `source` de cada entrada de `configs/models/`.

Los pesos se organizan por familia y linaje (`original/` vs `finetuned/<tag>/`);
cada peso tiene su entrada en el catálogo `configs/models/` (ver `models/README.md`).

## Dónde poner imágenes y videos

Colocar imágenes de prueba en `data/samples/images/` (`.jpg`, `.jpeg`, `.png`) y videos en `data/samples/videos/`. Ver los README de cada carpeta para las recomendaciones de curado del mini-dataset.

Para datasets pesados, usar `data/raw/` o `data/datasets/` (ignorados por Git).

## Levantar el servicio

El **modelo se carga una sola vez al startup** (no por run) a partir de la variable
`EOVRT_MODEL_REF` (una `ref` del catálogo `configs/models/`, o `mock` para validar el
pipeline sin pesos reales). **Correr siempre desde la raíz del media-plane** (los
catálogos de datasets usan rutas `../e-ovrt_datasets` relativas al CWD).

```bash
# Arranca uvicorn --factory sobre eovrt_media.service.app:create_app en :8080
EOVRT_MODEL_REF=mock make serve

# Smoke: verifica /healthz + /readyz
make smoke
```

Endpoints de salud y metadata:

```bash
curl -s http://localhost:8080/healthz          # liveness
curl -s http://localhost:8080/readyz           # readiness (modelo cargado)
curl -s http://localhost:8080/api/model        # ref/adaptador/device del modelo cargado
```

Variables de entorno relevantes: `EOVRT_MODEL_REF` (obligatoria), `EOVRT_RUNS_DIR`
(directorio de artefactos, default `runs/`), `EOVRT_MEDIA_CATALOG_ROOT`, `EOVRT_DATASETS_ROOT`,
`EOVRT_MODEL_DEVICE` (pisa el `device` del catálogo; ej. `cuda`/`cpu`),
`EOVRT_EVAL_IOU_THRESHOLD` (umbral IoU de la evaluación BENCH, default `0.5`).

El `device` de cada catálogo de modelo es **`auto`** por defecto (excepto `mock`, que
es `cpu` para tests deterministas): resuelve a `cuda` si hay GPU disponible y a `cpu` si
no, sin pedir configuración. `EOVRT_MODEL_DEVICE` lo fuerza explícitamente. El device
efectivamente resuelto es el que reportan `/api/model` y el `summary.json` de cada run.

## Disparar una corrida

El **modelo nunca viaja en el request**: es el que la instancia cargó al startup. El
body declara la **fuente de ingesta** (`ingest`) y los **prompts** (`prompts`). Los
plugins de ingesta disponibles se consultan en el catálogo:

```bash
curl -s http://localhost:8080/api/catalog/ingest-plugins   # image_folder, video_file, rtsp, oak_d
curl -s http://localhost:8080/api/catalog/datasets          # datasets referenciables por 'dataset'
```

Ejemplo mínimo — carpeta de imágenes + prompts inline:

```bash
curl -X POST http://localhost:8080/api/runs \
  -H "Content-Type: application/json" \
  -d '{
        "ingest": {"plugin": "image_folder", "config": {"path": "/ruta/a/imagenes"}},
        "prompts": {
          "set_inline": {
            "id": "demo",
            "classes": [{"id": "person", "phrasings": {"default": ["person"]}}]
          },
          "active_ids": ["person"]
        },
        "run": {"stride": 1, "max_units": 200, "save_previews": true}
      }'
# -> 201 {"run_id": "run_..."}
```

Notas:
- `ingest.plugin` puede ser `image_folder`, `video_file`, `rtsp` (vivo) o `oak_d`
  (advertido pero **no disponible** en Fase 1 → responde 4xx claro, no 500).
- Para usar un dataset del catálogo, pasar `config.dataset: <nombre>` en vez de `path`.
- Incluir una sección `model` en el body es un error (**422**): el modelo es fijo por instancia.
- Solo puede haber **un run activo**: un segundo `POST /api/runs` mientras hay uno en curso responde **409**.
- Para RTSP con credenciales inline (`rtsp://user:pass@host`), las URLs se **redactan**
  en logs y artefactos (`errors.jsonl`, `effective_config.yaml`) antes de persistirse.

### Consultar, transmitir y detener

```bash
# Estado/resumen de la corrida
curl -s http://localhost:8080/api/runs/<run_id>

# Listado (activo + historial en EOVRT_RUNS_DIR)
curl -s http://localhost:8080/api/runs

# Detener el run activo
curl -X POST http://localhost:8080/api/runs/<run_id>/stop    # 202

# Borrar un run terminado (409 si sigue activo)
curl -X DELETE http://localhost:8080/api/runs/<run_id>       # 204
```

### Evaluar un run BENCH por HTTP

Un run terminado hecho sobre un split del BENCH se evalúa desde el servicio (calcula
AP@0.5 por clase, CR-01 recall y mAP@0.5, y persiste `eval_perception.json`):

```bash
# Dispara la evaluación y devuelve el resultado enriquecido (mAP50/model/bench_split)
curl -X POST http://localhost:8080/api/runs/<run_id>/evaluate   # 200

# Relee el resultado ya persistido (404 si el run no fue evaluado)
curl -s http://localhost:8080/api/runs/<run_id>/evaluate        # 200
```

- **422** si el run no fue sobre un split del BENCH (`bench_split` nulo) o si falta el GT en disco.
- **409** si el run sigue en curso. El `GET /api/runs/<run_id>` expone `bench_split` y `evaluated`
  para saber de antemano si un run es evaluable y si ya tiene evaluación.

Stream de eventos en vivo (detecciones/métricas/estado) por WebSocket:

```
WS ws://localhost:8080/api/runs/<run_id>/stream
```

### Artefactos por HTTP

```bash
# Detecciones paginadas (JSON)
curl -s "http://localhost:8080/api/runs/<run_id>/detections?page=1&page_size=100"

# Archivos crudos del run (soporta Range para video)
curl -s http://localhost:8080/api/runs/<run_id>/artifacts/summary.json
curl -s http://localhost:8080/api/runs/<run_id>/artifacts/errors.jsonl
curl -s http://localhost:8080/api/runs/<run_id>/artifacts/previews/<archivo>.jpg
```

## Topología dos nodos (Nodo A edge + Nodo B GPU)

La ejecución distribuida (Nodo A: ingesta + normalización + ZeroMQ REP; Nodo B:
inferencia + artefactos + ZeroMQ REQ) se invoca **en proceso** vía
`runtime/two_node.py:run_node_a()` / `run_node_b()`; el config debe declarar
`topology.mode: two_node` (el loader deriva `transport.backend: network`). Ver
[docs/deployment/two-node-docker.md](deployment/two-node-docker.md) para el despliegue
con Docker Compose (Fase 2, `infra/twonode/`, ya completada y verificada).

> **No soportado en Fase 1:** el banco local nativo `run_two_node_local()` y la
> campaña `debug_run` en modo dos-nodos-local **spawneaban el CLI eliminado** y ahora
> fallan de forma explícita. Su reemplazo es el split two-node dockerizado de
> `infra/twonode/` (Fase 2); la ruta local queda deshabilitada permanentemente y no
> tiene puente hacia ese despliegue Docker.

## Leer resultados

Cada corrida genera un directorio en `EOVRT_RUNS_DIR` (default `runs/`):

```
runs/<run_id>/
├── run_config.yaml          # Copia de la configuración original
├── effective_config.yaml    # Configuración efectiva (defaults resueltos, URLs redactadas)
├── run_manifest.json        # Metadatos: run_id, fechas, commit del código, archivos
├── detections.jsonl         # Una línea JSON por unidad procesada
├── metrics.jsonl            # Métricas por unidad
├── errors.jsonl             # Errores recuperables
├── summary.json             # Resumen v2 y descriptor de despliegue
├── run_provenance.json      # Dataset, vocabulario y fingerprint de la fuente
└── previews/                # Previews anotados, cuando save_previews=true
```

`summary.json` incluye latencias avg/p50/p95/p99, FPS efectivo, descartes, espera de
backpressure, `run_descriptor`, desglose por label/prompt y VRAM máxima. `metrics.jsonl`
usa `media.metric.v2` e incluye latencia de normalización.

Con `save_previews: true`, el consumidor renderiza previews anotados directamente desde
`NormalizedUnit.payload`. Funciona con imágenes, vídeo, RTSP y en Nodo B sin acceso a la ruta
original del productor; las cajas se dibujan en el espacio del payload normalizado.

### Inspeccionar y comparar corridas (utilitarios)

```bash
python -m eovrt_media.tools.inspect_runs inspect runs/<run_id>
python -m eovrt_media.tools.inspect_runs compare runs/                 # tabla comparativa
python -m eovrt_media.tools.inspect_runs compare runs/<run_a> runs/<run_b>
```

Imprime una tabla comparativa (modelo, device, unidades, detecciones, latencias, FPS, VRAM pico) y el desglose de detecciones por label de cada corrida.

## Evaluar percepción (BENCH)

Tras ejecutar una corrida sobre imágenes del BENCH, calcule AP@0.5 por clase y CR-01 recall:

```bash
python -m eovrt_media.tools.evaluate --run runs/<run_id>
```

El comando auto-descubre los archivos del BENCH desde el repo hermano `../e-ovrt_datasets`.
Si los paths difieren, páselos explícitamente:

```bash
python -m eovrt_media.tools.evaluate \
  --run runs/<run_id> \
  --bench-coco ../e-ovrt_datasets/datasets/processed/coco/bench/construction_site_safety_bench.json \
  --person-gt  ../e-ovrt_datasets/datasets/processed/coco/bench/person_gt.json
```

Imprime una tabla con AP@0.5 y conteos por clase, CR-01 recall, y persiste
`runs/<run_id>/eval_perception.json` (`type: "perception"`).

> El CLI evalúa contra el **GT completo del BENCH** (val+test combinados, pensado para
> `--detections` de varios splits a la vez). El endpoint HTTP `POST .../evaluate` en
> cambio **restringe el GT a las imágenes que el run realmente procesó**, para que un run
> de un solo split (p.ej. `bench_v2_test`) obtenga `n_gt`/AP@0.5 no deflactados. Para
> comparar modelos por la consola, use siempre el endpoint HTTP.

## Knobs de rendimiento

### Inferencia — fp16 y warmup

Cada entrada del catálogo de modelo (`configs/models/<familia>/<variante>.yaml`) acepta
un bloque `runtime` opcional:

```yaml
runtime:
  half_precision: true   # fp16 (autocast en GDINO, half= en YOLOE); ignorado en CPU
  warmup: true           # inferencia dummy al cargar; reduce latencia del primer frame
```

**Defaults:** `half_precision: true`, `warmup: true` cuando el bloque se omite.
El constructor del adaptador usa `false`/`false` si se instancia directamente (seguro en CPU).

**fp16 en CPU es un no-op** — el flag se ignora automáticamente cuando `device` no es CUDA.

**Reproducibilidad del BENCH:** fp16 puede mover levemente los scores de confianza y,
con ello, el AP@0.5. Las corridas canónicas del BENCH deben fijar `half_precision`
explícitamente en el config del experimento para que los resultados sean reproducibles.

### Transporte de red — compresión JPEG

La topología dos nodos acepta un bloque de compresión en la sección `transport`:

```yaml
transport:
  compression:
    codec: jpeg    # jpeg | raw  (default: jpeg para el transporte de red)
    quality: 90    # 1–100; solo aplica si codec=jpeg
```

El codec viaja en el header del wire (autodescriptivo), por lo que el consumidor no
necesita configuración. El payload FP32 cae automáticamente a `raw` con un warning.

El camino single-host (`transport.backend: memory`) **no se ve afectado** — las
corridas DBE reproducibles nunca pasan por compresión lossy.

## Linting y tests

```bash
make lint    # ruff check src tests
make test    # pytest -q
```
