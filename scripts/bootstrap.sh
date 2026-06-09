#!/usr/bin/env bash
# bootstrap.sh — Configuración inicial del entorno de desarrollo.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_DIR"

echo "=== E-OVRT Media Plane — Bootstrap ==="

# Crear entorno virtual si no existe
if [ ! -d ".venv" ]; then
    echo "[1/3] Creando entorno virtual..."
    python3.11 -m venv .venv
else
    echo "[1/3] Entorno virtual ya existe."
fi

echo "[2/3] Activando entorno e instalando dependencias..."
source .venv/bin/activate
python -m pip install --upgrade pip setuptools wheel --quiet
pip install -e ".[dev]" --quiet

echo "[3/3] Verificando instalación..."
eovrt-media --help

echo ""
echo "=== Bootstrap completo ==="
echo "Activar entorno: source .venv/bin/activate"
