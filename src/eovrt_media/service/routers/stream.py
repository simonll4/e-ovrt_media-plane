"""Streaming de telemetría por WebSocket con coalescing (Spec A §3.1)."""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, WebSocket

from eovrt_media.service.run_ids import is_valid_run_id
from eovrt_media.service.run_manager import UnknownRunError

router = APIRouter(prefix="/api")

_POLL_SECONDS = 0.2


@router.websocket("/runs/{run_id}/stream")
async def stream_run(ws: WebSocket, run_id: str) -> None:
    if not is_valid_run_id(run_id):
        # run_id inválido (p.ej. traversal '..'): mismo cierre que "run
        # desconocido", sin tocar el filesystem (ver runs.py _require_valid_run_id).
        await ws.accept()
        await ws.close(code=4404)
        return
    manager = getattr(ws.app.state, "manager", None)
    if manager is None:
        await ws.accept()
        await ws.close(code=4503)
        return
    try:
        info = manager.get(run_id)
    except UnknownRunError:
        await ws.accept()
        await ws.close(code=4404)
        return

    await ws.accept()
    if info["status"] != "running":
        await ws.send_json({"type": "state", "status": info["status"]})
        await ws.close()
        return

    try:
        sub = manager.subscribe(run_id)
    except UnknownRunError:
        # terminó entre el get y el subscribe
        await ws.send_json({"type": "state", "status": manager.get(run_id)["status"]})
        await ws.close()
        return

    try:
        while True:
            for event in sub.drain():
                await ws.send_json(event)
            status = manager.get(run_id)["status"]
            if status != "running":
                # Flush final: entre el drain de arriba y este chequeo de status
                # pudieron llegar eventos (incluido el "state" propio del
                # broadcaster) a la cola del subscriber; drenarlos antes de
                # cerrar evita perder la cola de eventos (puede duplicar el
                # "state" final, aceptable — el cliente coalesce por type).
                for event in sub.drain():
                    await ws.send_json(event)
                await ws.send_json({"type": "state", "status": status})
                break
            await asyncio.sleep(_POLL_SECONDS)
    finally:
        manager.unsubscribe(run_id, sub)
        await ws.close()
