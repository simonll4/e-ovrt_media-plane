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

Esto descarga:
1. **Grounding DINO tiny** desde Hugging Face → `models/grounding-dino/grounding-dino-tiny/`
2. **YOLOE small** desde Ultralytics → `models/yoloe/yoloe-26s-seg.pt`

## Dónde poner imágenes

Colocar imágenes de prueba en:

```
data/samples/images/
```

Formatos soportados: `.jpg`, `.jpeg`, `.png`.

Para datasets pesados, usar `data/raw/` o `data/datasets/` (ignorados por Git).

## Ejecutar pipeline

### Con Grounding DINO

```bash
eovrt-media run --config configs/dbe_grounding_dino_cr01_cr02.yaml
# o
make run-gdino
```

### Con YOLOE

```bash
eovrt-media run --config configs/dbe_yoloe_cr01_cr02.yaml
# o
make run-yoloe
```

### Con detector mock (para testing)

Cambiar `model.adapter` a `mock` en el YAML de configuración.

## Leer resultados

Cada corrida genera un directorio en `runs/`:

```
runs/<run_id>/
├── effective_config.yaml    # Configuración usada
├── detections.jsonl         # Una línea JSON por imagen procesada
├── metrics.jsonl            # Métricas por imagen
├── summary.json             # Resumen de la corrida
└── previews/                # Imágenes anotadas con bounding boxes
```

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

## Linting y tests

```bash
make lint    # ruff check
make test    # pytest
```
