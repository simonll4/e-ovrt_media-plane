"""API de control de runs (Spec A §3.1)."""
from __future__ import annotations

import json as _json
import shutil

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse, Response

from eovrt_media.evaluation.runner import run_evaluation
from eovrt_media.evaluation.schemas import ClassResult
from eovrt_media.service.run_ids import require_valid_run_id as _require_valid_run_id
from eovrt_media.service.run_manager import RunBusyError, RunManager, UnknownRunError
from eovrt_media.service.run_request import RunRequest
from eovrt_media.sinks.jsonl_sink import atomic_write_json

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
    _require_valid_run_id(run_id)
    try:
        return _manager(request).get(run_id)
    except UnknownRunError as exc:
        raise HTTPException(status_code=404, detail=f"Run desconocido: {run_id}") from exc


@router.post("/runs/{run_id}/stop", status_code=202)
def stop_run(run_id: str, request: Request):
    _require_valid_run_id(run_id)
    try:
        _manager(request).stop(run_id)
    except UnknownRunError as exc:
        raise HTTPException(status_code=404, detail=f"Run desconocido: {run_id}") from exc
    return {"run_id": run_id, "stopping": True}


@router.delete("/runs/{run_id}", status_code=204)
def delete_run(run_id: str, request: Request):
    _require_valid_run_id(run_id)
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


@router.get("/runs/{run_id}/detections")
def get_detections(
    run_id: str,
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(100, ge=1, le=1000),
):
    _manager(request)  # 503 si no ready
    _require_valid_run_id(run_id)
    path = request.app.state.settings.runs_dir / run_id / "detections.jsonl"
    try:
        text = path.read_text()
    except FileNotFoundError as exc:
        # TOCTOU: un DELETE concurrente puede borrar el archivo entre un
        # chequeo previo de existencia y esta lectura; se trata como 404
        # en vez de dejar propagar un 500.
        raise HTTPException(
            status_code=404, detail=f"Sin detecciones para: {run_id}"
        ) from exc
    records = []
    for line in text.splitlines():
        if not line:
            continue
        try:
            records.append(_json.loads(line))
        except ValueError:
            continue  # línea malformada: se omite en vez de 500
    start = (page - 1) * page_size
    items = records[start : start + page_size]
    return {"page": page, "page_size": page_size, "total": len(records), "items": items}


@router.get("/runs/{run_id}/artifacts/{artifact_path:path}")
def get_artifact(run_id: str, artifact_path: str, request: Request):
    _require_valid_run_id(run_id)
    run_dir = (request.app.state.settings.runs_dir / run_id).resolve()
    try:
        target = (run_dir / artifact_path).resolve()
        is_valid = target.is_relative_to(run_dir) and target.is_file()
    except (ValueError, OSError):
        # path hostil (p.ej. byte nulo embebido) no distinguible de "no encontrado"
        is_valid = False
    if not is_valid:
        raise HTTPException(status_code=404, detail="Artefacto no encontrado")
    return FileResponse(target)  # Starlette >=0.36 maneja Range (206) para video


def _mean_ap50(per_class: list[ClassResult]) -> float | None:
    """mAP@0.5 = media de los AP50 no-nulos (incluye 0.0 de clases con GT y
    0 matches; excluye clases sin GT). None si ninguna clase tiene GT."""
    values = [item.AP50 for item in per_class if item.AP50 is not None]
    return round(sum(values) / len(values), 4) if values else None


@router.post("/runs/{run_id}/evaluate")
def evaluate_run(run_id: str, request: Request):
    _require_valid_run_id(run_id)
    manager = _manager(request)
    try:
        info = manager.get(run_id)
    except UnknownRunError as exc:
        raise HTTPException(status_code=404, detail=f"Run desconocido: {run_id}") from exc
    if info["status"] == "running":
        raise HTTPException(status_code=409, detail="No se evalúa un run en curso")
    if info.get("bench_split") is None:
        raise HTTPException(
            status_code=422, detail="El run no fue sobre un split del BENCH (no evaluable)"
        )
    run_dir = request.app.state.settings.runs_dir / run_id
    try:
        result = run_evaluation(
            run_dir,
            iou_threshold=request.app.state.settings.eval_iou_threshold,
            restrict_gt_to_detections=True,
            persist=False,
        )
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=422,
            detail=(
                "No se pudo evaluar: falta el GT del BENCH o detections.jsonl. "
                "Verificá que ../e-ovrt_datasets exista como hermano del media-plane "
                "(y corré build_person_gt.py si falta person_gt.json). "
                f"Causa: {exc}"
            ),
        ) from exc
    payload = result.model_dump(mode="json")
    payload["mAP50"] = _mean_ap50(result.per_class)
    payload["model"] = (info.get("summary") or {}).get("model_name")
    payload["bench_split"] = info["bench_split"]
    # El endpoint es dueño de la persistencia enriquecida y atómica (una sola
    # escritura; run_evaluation se llamó con persist=False).
    atomic_write_json(run_dir / "eval_perception.json", payload)
    return payload


@router.get("/runs/{run_id}/evaluate")
def get_evaluation(run_id: str, request: Request):
    _require_valid_run_id(run_id)
    _manager(request)  # 503 si no ready
    path = request.app.state.settings.runs_dir / run_id / "eval_perception.json"
    try:
        return _json.loads(path.read_text())
    except (OSError, ValueError) as exc:
        # No evaluado, borrado concurrente o JSON ilegible: mismo trato (404).
        raise HTTPException(status_code=404, detail=f"Run no evaluado: {run_id}") from exc
