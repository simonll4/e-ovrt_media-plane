"""Endpoints de liveness/readiness para el contenedor."""
from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

router = APIRouter()


@router.get("/healthz")
def healthz() -> dict:
    return {"status": "ok"}


@router.get("/readyz")
def readyz(request: Request):
    if getattr(request.app.state, "ready", False):
        model = getattr(request.app.state, "model_section", None)
        return {"status": "ready", "model": model.ref if model else None}
    return JSONResponse(
        status_code=503,
        content={"status": "not_ready", "error": getattr(request.app.state, "load_error", None)},
    )
