"""Descarga y compila el blob RVC2 del detector de personas del prefilter EN-2.

Modelo: person-detection-retail-0013 (Open Model Zoo, Apache-2.0), 544x320,
2.3 GFLOPs — spec 2026-07-15 §3. Compilado para 6 SHAVEs vía blobconverter.
Requiere red; el blob (~3 MB) queda git-ignorado como el resto de los pesos.
"""
from __future__ import annotations

from pathlib import Path

import blobconverter

REPO_ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = REPO_ROOT / "models" / "edge"
TARGET = OUT_DIR / "person-detection-retail-0013_6shave.blob"


def main() -> None:
    if TARGET.exists():
        print(f"Ya existe: {TARGET}")
        return
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    blob = blobconverter.from_zoo(
        name="person-detection-retail-0013",
        zoo_type="intel",
        shaves=6,
        output_dir=str(OUT_DIR),
    )
    # blobconverter agrega sufijos de versión OpenVINO al nombre: renombrar al
    # nombre canónico que espera el default del schema.
    Path(blob).replace(TARGET)
    print(f"Blob listo: {TARGET}")


if __name__ == "__main__":
    main()
