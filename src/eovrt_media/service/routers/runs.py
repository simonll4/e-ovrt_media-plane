"""API de control de runs (Spec A §3.1)."""
from __future__ import annotations

import shutil

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, Response

from eovrt_media.service.run_manager import RunBusyError, RunManager, UnknownRunError
from eovrt_media.service.run_request import RunRequest

router = APIRouter(prefix="/api")


def _manager(request: Request) -> RunManager:
    if not getattr(request.app.state, "ready", False):
        raise HTTPException(status_code=503, detail="Servicio no listo (modelo no cargado)")
    return request.app.state.manager


@router.post("/runs", status_code=201)
def create_run(body: RunRequest, request: Request):
    manager = _manager(request)
    try:
        run_id = manager.start_run(body)
    except RunBusyError as exc:
        return JSONResponse(
            status_code=409,
            content={"detail": str(exc), "active_run_id": exc.active_run_id},
        )
    except (ValueError, FileNotFoundError) as exc:
        # errores del loader/registro (config inválida, ref inexistente, plugin no disponible)
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"run_id": run_id}


@router.get("/runs")
def list_runs(request: Request):
    return _manager(request).list_runs()


@router.get("/runs/{run_id}")
def get_run(run_id: str, request: Request):
    try:
        return _manager(request).get(run_id)
    except UnknownRunError as exc:
        raise HTTPException(status_code=404, detail=f"Run desconocido: {run_id}") from exc


@router.post("/runs/{run_id}/stop", status_code=202)
def stop_run(run_id: str, request: Request):
    try:
        _manager(request).stop(run_id)
    except UnknownRunError as exc:
        raise HTTPException(status_code=404, detail=f"Run desconocido: {run_id}") from exc
    return {"run_id": run_id, "stopping": True}


@router.delete("/runs/{run_id}", status_code=204)
def delete_run(run_id: str, request: Request):
    manager = _manager(request)
    try:
        info = manager.get(run_id)
    except UnknownRunError as exc:
        raise HTTPException(status_code=404, detail=f"Run desconocido: {run_id}") from exc
    if info["status"] == "running":
        raise HTTPException(status_code=409, detail="No se puede borrar un run activo")
    run_dir = request.app.state.settings.runs_dir / run_id
    shutil.rmtree(run_dir, ignore_errors=True)
    return Response(status_code=204)
