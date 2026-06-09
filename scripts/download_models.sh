#!/usr/bin/env bash
# download_models.sh — Descarga pesos de modelos para el plano de medios.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_DIR"

echo "=== Descarga de modelos ==="

mkdir -p models/grounding-dino/grounding-dino-tiny
mkdir -p models/yoloe

printf "\n[1/2] Descargando Grounding DINO tiny desde Hugging Face...\n"
hf download IDEA-Research/grounding-dino-tiny \
  --local-dir models/grounding-dino/grounding-dino-tiny

printf "\n[2/2] Preparando YOLOE small desde Ultralytics...\n"
python - <<'PY'
from pathlib import Path
from ultralytics import YOLOE

out_dir = Path("models/yoloe")
out_dir.mkdir(parents=True, exist_ok=True)

# Ultralytics descarga automáticamente el checkpoint si no existe localmente.
model = YOLOE("yoloe-26s-seg.pt")

# Si el archivo queda en el directorio actual, se mueve a models/yoloe.
src = Path("yoloe-26s-seg.pt")
dst = out_dir / "yoloe-26s-seg.pt"
if src.exists() and not dst.exists():
    src.rename(dst)

print("YOLOE listo")
PY

printf "\nModelos preparados.\n"
