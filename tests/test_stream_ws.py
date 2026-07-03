import time
import pytest
from PIL import Image
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect
from eovrt_media.service.app import create_app
from eovrt_media.service.settings import ServiceSettings

SET_INLINE = {"id": "t", "classes": [{"id": "p", "phrasings": {"default": ["p"]}}]}


@pytest.fixture()
def client(tmp_path):
    settings = ServiceSettings.from_env(
        {"EOVRT_MODEL_REF": "mock", "EOVRT_RUNS_DIR": str(tmp_path / "runs")}
    )
    with TestClient(create_app(settings)) as c:
        yield c


def _launch(client, tmp_path, n=100):
    folder = tmp_path / "imgs"
    folder.mkdir(exist_ok=True)
    for i in range(n):
        Image.new("RGB", (64, 48), (1, 2, 3)).save(folder / f"i{i:03d}.png")
    body = {
        "ingest": {"plugin": "image_folder", "config": {"path": str(folder)}},
        "prompts": {"set_inline": SET_INLINE},
        "run": {},
    }
    return client.post("/api/runs", json=body).json()["run_id"]


def test_stream_emite_y_termina_con_estado(client, tmp_path):
    run_id = _launch(client, tmp_path)
    received = []
    with client.websocket_connect(f"/api/runs/{run_id}/stream") as ws:
        while True:
            try:
                received.append(ws.receive_json())
            except WebSocketDisconnect:
                break
            if received and received[-1].get("type") == "state":
                break
    assert received[-1]["type"] == "state"
    assert received[-1]["status"] in {"succeeded", "stopped", "failed"}


def test_stream_run_desconocido_cierra_4404(client):
    with pytest.raises(WebSocketDisconnect) as excinfo:
        with client.websocket_connect("/api/runs/nope/stream") as ws:
            ws.receive_json()
    assert excinfo.value.code == 4404


def test_stream_run_terminado_envia_estado_final(client, tmp_path):
    run_id = _launch(client, tmp_path, n=3)
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if client.get(f"/api/runs/{run_id}").json()["status"] != "running":
            break
        time.sleep(0.05)
    with client.websocket_connect(f"/api/runs/{run_id}/stream") as ws:
        msg = ws.receive_json()
    assert msg["type"] == "state" and msg["status"] != "running"


def test_stream_no_pierde_cola_final_de_eventos(client, tmp_path):
    """Regresión (caracterización general, no determinística): el drain de
    tope de loop puede correr antes de que el worker empuje sus últimos
    eventos (detection/metric/state) y antes de que el status pase a
    terminal. Este test conecta al stream apenas se lanza la run (mientras
    sigue "running") y verifica que TODOS los `detection` esperados llegan,
    no solo que llega un `state` final. La ventana de carrera real es
    demasiado angosta para forzarla de forma fiable con timing natural —
    ver `test_stream_flush_final_evita_perder_evento_en_ventana_de_carrera`
    para una reproducción determinística de la carrera puntual que motivó
    el fix.
    """
    n = 40
    run_id = _launch(client, tmp_path, n=n)
    received = []
    with client.websocket_connect(f"/api/runs/{run_id}/stream") as ws:
        while True:
            try:
                msg = ws.receive_json()
            except WebSocketDisconnect:
                break
            received.append(msg)
            if msg.get("type") == "state":
                break

    assert received, "no se recibió ningún evento"
    assert received[-1]["type"] == "state"
    assert received[-1]["status"] in {"succeeded", "stopped", "failed"}

    detection_unit_ids = {m["unit_id"] for m in received if m.get("type") == "detection"}
    assert len(detection_unit_ids) == n, (
        f"se esperaban {n} eventos 'detection' (uno por unidad procesada); "
        f"llegaron {len(detection_unit_ids)} — la cola de eventos se cortó "
        "antes del cierre del stream"
    )


def test_stream_flush_final_evita_perder_evento_en_ventana_de_carrera(
    client, tmp_path, monkeypatch
):
    """Reproducción determinística de la carrera del finding: un evento
    llega a la cola del Subscriber exactamente en la ventana entre el drain
    de tope de loop y la lectura de `manager.get(run_id)["status"]` que lo
    detecta terminal. Se instrumenta `manager.get` para, la primera vez que
    devolvería un status terminal, empujar un evento marcador a la cola del
    Subscriber real (capturado vía `manager.subscribe`) justo antes de
    devolver ese status — esto es exactamente lo que hace el hilo worker en
    `RunManager._finalize` (fija `active.status` y luego emite el evento
    `state`) si se cuela en ese instante. Sin el flush final agregado antes
    del `break`, ese evento marcador quedaría atascado en la cola y jamás se
    enviaría por el WebSocket.
    """
    run_id = _launch(client, tmp_path, n=3)
    manager = client.app.state.manager

    captured: dict[str, object] = {}
    original_subscribe = manager.subscribe

    def fake_subscribe(rid):
        sub = original_subscribe(rid)
        captured["sub"] = sub
        return sub

    monkeypatch.setattr(manager, "subscribe", fake_subscribe)

    original_get = manager.get
    injected = {"done": False}
    marker = {"type": "detection", "unit_id": "__race_marker__", "count": 1}

    def fake_get(rid):
        result = original_get(rid)
        if not injected["done"] and result["status"] != "running" and "sub" in captured:
            # Simula el evento que un hilo worker concurrente empuja
            # exactamente entre el drain de tope de loop y este chequeo de
            # status (ver RunManager._finalize: status se fija ANTES del
            # broadcaster.emit del evento "state" final).
            captured["sub"].push(marker)  # type: ignore[union-attr]
            injected["done"] = True
        return result

    monkeypatch.setattr(manager, "get", fake_get)

    # No cortamos en el primer "state": el drenaje real puede repartirse en
    # más de un batch (el "state" propio del broadcaster puede llegar en el
    # drain de tope de loop, ANTES de que el chequeo de status dispare la
    # inyección del marcador, que se envía recién en el flush final). Cortar
    # en el primer "state" daría un falso negativo — hay que leer hasta que
    # el servidor cierre la conexión para ver la cola completa.
    received = []
    with client.websocket_connect(f"/api/runs/{run_id}/stream") as ws:
        while True:
            try:
                msg = ws.receive_json()
            except WebSocketDisconnect:
                break
            received.append(msg)

    assert injected["done"], "el test no logró forzar la ventana de carrera"
    assert received, "no se recibió ningún evento"
    assert received[-1]["type"] == "state"
    assert any(m.get("unit_id") == "__race_marker__" for m in received), (
        "el evento inyectado en la ventana de carrera (entre el drain de tope "
        "de loop y el chequeo de status) se perdió — falta el flush final del "
        "buffer antes de enviar el estado terminal y cerrar"
    )
