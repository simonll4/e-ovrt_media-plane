#!/usr/bin/env bash
# download_models.sh — Descarga los pesos originales de la matriz experimental.
# Los pesos quedan bajo models/<familia>/original/ según la convención del
# catálogo (ver models/README.md y configs/models/). Fuentes documentadas en
# models/README.md y en el campo `source` de cada entrada de catálogo.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_DIR"

echo "=== Descarga de modelos ==="

mkdir -p models/grounding-dino/original models/mm-grounding-dino/original models/yoloe/original

printf "\n[1/4] Grounding DINO tiny desde Hugging Face...\n"
hf download IDEA-Research/grounding-dino-tiny \
  --local-dir models/grounding-dino/original/grounding-dino-tiny

printf "\n[2/4] Grounding DINO base desde Hugging Face...\n"
hf download IDEA-Research/grounding-dino-base \
  --local-dir models/grounding-dino/original/grounding-dino-base

printf "\n[3/4] MM-Grounding-DINO (tiny/base/large) desde Hugging Face...\n"
for repo in mm_grounding_dino_tiny_o365v1_goldg_v3det mm_grounding_dino_base_all mm_grounding_dino_large_all; do
  hf download "openmmlab-community/$repo" \
    --local-dir "models/mm-grounding-dino/original/$repo"
done

printf "\n[4/4] YOLOE-26 (s/m/l/x) desde Ultralytics release assets...\n"
python - <<'PY'
from pathlib import Path
from ultralytics.utils.downloads import attempt_download_asset

out_dir = Path("models/yoloe/original")
out_dir.mkdir(parents=True, exist_ok=True)

for name in ["yoloe-26s-seg.pt", "yoloe-26m-seg.pt", "yoloe-26l-seg.pt", "yoloe-26x-seg.pt"]:
    dst = out_dir / name
    if dst.exists():
        print(f"ya existe: {dst}")
        continue
    path = attempt_download_asset(name)
    Path(path).rename(dst)
    print(f"descargado: {dst}")

print("YOLOE listo")
PY

printf "\nModelos preparados.\n"
