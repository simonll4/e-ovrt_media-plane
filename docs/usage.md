# Uso del Plano de Medios

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

# Verificar
eovrt-media --help
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

## Ejecutar pipeline

Las run configs viven en `configs/runs/` y componen los catálogos de
`configs/models/`, `configs/datasets/` y `configs/prompts/` por referencia
(ver `configs/README.md` para la anatomía completa y cómo armar una nueva).

### Con detector mock (validación sin modelos reales)

```bash
eovrt-media run --config configs/runs/mock.yaml
# o
make run-mock
```

La config `mock.yaml` usa el catálogo `demo_v2` (CHV demo v2, repo hermano
`../e-ovrt_datasets`). No requiere pesos de modelos; valida el pipeline completo con
el detector mock. Asegúrese de que el repo hermano esté presente como sibling en disco.

### Con Grounding DINO

```bash
eovrt-media run --config configs/runs/gdino.yaml
# o
make run-gdino
```

### Con YOLOE

```bash
eovrt-media run --config configs/runs/yoloe.yaml
# o
make run-yoloe
```

### Con stride (muestreo por paso)

```bash
eovrt-media run --config configs/runs/yoloe_video.yaml
```

Procesa CHV demo v2 con `stride: 5` (1 de cada 5 imágenes). El stride se controla
con `rate_control.stride` y el límite de unidades con `run.max_units`. La sección
`sampling` ya no es válida; el loader informa cómo migrarla.

### Topología dos nodos (Nodo A edge + Nodo B GPU)

```bash
# Nodo A: ingesta + normalización + ZeroMQ REP
eovrt-media run-producer --config configs/runs/<archivo>.yaml

# Nodo B: inferencia + artefactos + ZeroMQ REQ
eovrt-media run-consumer --config configs/runs/<archivo>.yaml
```

El config del run debe declarar `topology.mode: two_node`; el loader deriva
automáticamente `transport.backend: network`. Ver
[docs/deployment/two-node-docker.md](deployment/two-node-docker.md) para el
despliegue con Docker Compose.

### Cámara RTSP con YOLOE en GPU (single-host)

Guarde las configuraciones operativas locales en `configs/runs/local/`; este directorio
está ignorado por Git. La URI RTSP no debe versionarse ni incluirse en tickets. Para la
cámara, use el modelo `yoloe/yoloe-26s` con `device: cuda:0`, `source.type: rtsp` y
`rate_control.policy: bounded_freshness`.

```bash
python scripts/probe_rtsp.py --config configs/runs/local/ezviz_yoloe_rtsp.yaml --frames 30
eovrt-media run --config configs/runs/local/ezviz_yoloe_rtsp.yaml
```

Todo el directorio `runs/<run_id>/` puede contener la URI RTSP, incluidos
`run_config.yaml`, `effective_config.yaml`, `detections.jsonl`, `metrics.jsonl` y
`errors.jsonl`; manténgalo local o sanitícelo antes de compartirlo.

## Leer resultados

Cada corrida genera un directorio en `runs/`:

```
runs/<run_id>/
├── run_config.yaml          # Copia de la configuración original
├── effective_config.yaml    # Configuración efectiva (defaults resueltos)
├── run_manifest.json        # Metadatos: run_id, fechas, commit del código, archivos
├── detections.jsonl         # Una línea JSON por unidad procesada
├── metrics.jsonl            # Métricas por unidad
├── errors.jsonl             # Errores recuperables
├── summary.json             # Resumen v2 y descriptor de despliegue
├── run_provenance.json      # Dataset, vocabulario y fingerprint de la fuente
└── previews/                # Directorio reservado para previews
```

`summary.json` incluye latencias avg/p50/p95/p99, FPS efectivo, descartes, espera de
backpressure, `run_descriptor`, desglose por label/prompt y VRAM máxima. `metrics.jsonl`
usa `media.metric.v2` e incluye latencia de normalización.

Con `save_previews: true`, el pipeline renderiza previews anotadas para fuentes de imagen.
La renderización de previews de frames de vídeo sigue pendiente.

### Ver resumen

```bash
cat runs/<run_id>/summary.json | python -m json.tool
```

### Ver detecciones

```bash
head -5 runs/<run_id>/detections.jsonl
```

### Inspeccionar corrida

```bash
eovrt-media inspect-run runs/<run_id>
```

### Comparar corridas

```bash
eovrt-media compare-runs runs/                      # todas las corridas bajo runs/
eovrt-media compare-runs runs/<run_a> runs/<run_b>  # corridas específicas
# o
make compare-runs
```

Imprime una tabla comparativa (modelo, device, unidades, detecciones, latencias, FPS, VRAM pico) y el desglose de detecciones por label de cada corrida.

## Linting y tests

```bash
make lint    # ruff check
make test    # pytest
```
