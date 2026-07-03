"""Validación compartida de ``run_id`` como segmento de path del filesystem.

``run_id`` se usa para construir rutas bajo ``runs_dir`` (REST y WebSocket).
Se restringe a alfanuméricos, ``_`` y ``-``: esto descarta ``..``, ``/`` y
demás antes de construir cualquier ruta (defensa en profundidad frente a la
normalización de proxies/clientes).
"""
from __future__ import annotations

import re

from fastapi import HTTPException

RUN_ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")


def is_valid_run_id(run_id: str) -> bool:
    return bool(RUN_ID_RE.match(run_id))


def require_valid_run_id(run_id: str) -> None:
    """Levanta HTTPException 404 (patrón REST: "run desconocido") si inválido."""
    if not is_valid_run_id(run_id):
        raise HTTPException(status_code=404, detail=f"Run desconocido: {run_id}")
