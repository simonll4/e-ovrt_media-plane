"""Endpoints de la sesión de preview (sin persistencia)."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse

from eovrt_media.service.activity_slot import SlotBusyError
from eovrt_media.service.preview_manager import PreviewManager
from eovrt_media.service.preview_request import PreviewRequest

router = APIRouter(prefix="/api")

_POLL_SECONDS = 1 / 15


def _manager(request: Request) -> PreviewManager:
    if not getattr(request.app.state, "ready", False):
        raise HTTPException(status_code=503, detail="Servicio no listo (modelo no cargado)")
    return request.app.state.preview


@router.post("/preview", status_code=201)
def start_preview(body: PreviewRequest, request: Request):
    manager = _manager(request)
    try:
        preview_id = manager.start(body)
    except SlotBusyError as exc:
        content: dict = {"detail": str(exc)}
        if exc.owner_kind == "run":
            content["reason"] = "run_active"
            content["active_run_id"] = exc.owner_id
        else:
            content["reason"] = "preview_active"
        return JSONResponse(status_code=409, content=content)
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"preview_id": preview_id}


@router.get("/preview")
def preview_status(request: Request):
    return _manager(request).status()


@router.delete("/preview", status_code=204)
def stop_preview(request: Request):
    _manager(request).stop()


@router.websocket("/preview/stream")
async def stream_preview(ws: WebSocket) -> None:
    manager: PreviewManager | None = getattr(ws.app.state, "preview", None)
    if manager is None:
        await ws.accept()
        await ws.close(code=4503)
        return
    if not manager.is_active():
        await ws.accept()
        await ws.close(code=4404)
        return
    await ws.accept()
    last_seq = 0
    try:
        while True:
            status, seq, latest, error = manager.snapshot()
            if status != "streaming":
                await ws.send_json({"type": "state", "status": status, "error": error})
                break
            if seq != last_seq and latest is not None:
                await ws.send_bytes(latest)
                last_seq = seq
            await asyncio.sleep(_POLL_SECONDS)
    except WebSocketDisconnect:
        return
    await ws.close()
