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
