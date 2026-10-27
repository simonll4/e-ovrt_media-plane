#!/usr/bin/env bash
# download_models.sh — Descarga los pesos originales de la matriz experimental.
# Los pesos quedan bajo models/<familia>/original/ según la convención del
# catálogo (ver models/README.md y configs/models/). Fuentes documentadas en
# models/README.md y en el campo `source` de cada entrada de catálogo.
#
# ✎ 2026-10-27: versiones FIJADAS, para que otra máquina baje exactamente los mismos bytes
# con los que se midió (verificado contra las huellas de los pesos en uso):
#   - Grounding DINO: revisión del Hub de cada repo (la que tenía `main` al descargar);
#   - YOLOE-26 y sus auxiliares: release `v8.4.0` de ultralytics/assets (el digest sha256
#     que publica GitHub para cada asset coincide con el de los pesos en uso).
# El blob del prefiltro de la OAK-D se baja aparte (`make download-prefilter-blob`) y los
# checkpoints del ajuste fino no se descargan: vienen del paquete de evidencia (README).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_DIR"

GDINO_TINY_REV="a2bb814dd30d776dcf7e30523b00659f4f141c71"
GDINO_BASE_REV="12bdfa3120f3e7ec7b434d90674b3396eccf88eb"
ULTRALYTICS_RELEASE="v8.4.0"

echo "=== Descarga de modelos ==="

mkdir -p models/grounding-dino/original models/yoloe/original

printf "\n[1/3] Grounding DINO tiny desde Hugging Face (revisión %s)...\n" "$GDINO_TINY_REV"
hf download IDEA-Research/grounding-dino-tiny --revision "$GDINO_TINY_REV" \
  --local-dir models/grounding-dino/original/grounding-dino-tiny

printf "\n[2/3] Grounding DINO base desde Hugging Face (revisión %s)...\n" "$GDINO_BASE_REV"
hf download IDEA-Research/grounding-dino-base --revision "$GDINO_BASE_REV" \
  --local-dir models/grounding-dino/original/grounding-dino-base

# MM-Grounding-DINO (tiny/base/large) se descargaba acá; la familia se archivó
# el 2026-08-19 (catálogos en configs/_archive/mm-grounding-dino/, ver su README).

printf "\n[3/3] YOLOE-26 (s/m/l/x) y sus auxiliares desde ultralytics/assets %s...\n" "$ULTRALYTICS_RELEASE"
ULTRALYTICS_RELEASE="$ULTRALYTICS_RELEASE" python - <<'PY'
import os
from pathlib import Path
from ultralytics.utils.downloads import attempt_download_asset

release = os.environ["ULTRALYTICS_RELEASE"]
out_dir = Path("models/yoloe/original")
out_dir.mkdir(parents=True, exist_ok=True)

# mobileclip2_b.ts: encoder de texto de los prompts de YOLOE (el compose lo monta como
# /app/mobileclip2_b.ts). yolo26n.pt: lo pide Ultralytics en su primera corrida.
nombres = ["yoloe-26s-seg.pt", "yoloe-26m-seg.pt", "yoloe-26l-seg.pt", "yoloe-26x-seg.pt",
           "mobileclip2_b.ts", "yolo26n.pt"]
for name in nombres:
    dst = out_dir / name
    if dst.exists():
        print(f"ya existe: {dst}")
        continue
    path = attempt_download_asset(name, release=release)
    Path(path).rename(dst)
    print(f"descargado: {dst}")

print("YOLOE listo")
PY

printf "\nModelos preparados. Verificar con la lista de huellas de los pesos (sha256sum -c).\n"
