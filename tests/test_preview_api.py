import json
import shutil
import struct

import pytest
from fastapi.testclient import TestClient
from PIL import Image

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


def _images(tmp_path, n=5, size=(64, 48)):
    folder = tmp_path / "imgs"
    folder.mkdir(exist_ok=True)
    # Codificar un único PNG y copiar sus bytes al resto: el contenido de cada
    # imagen no importa para estos tests (nadie assertea píxeles), y encodear
    # n veces con PIL es el costo dominante cuando n/size crecen (F3: se
    # necesitan muchas imágenes más grandes para que la sesión de preview siga
    # viva el tiempo suficiente sin que el test se vuelva lento).
    first = folder / "f00000.png"
    Image.new("RGB", size, (10, 2, 3)).save(first)
    for i in range(1, n):
        shutil.copyfile(first, folder / f"f{i:05d}.png")
    return folder


def _preview_body(folder, mode="raw"):
    body = {"mode": mode, "ingest": {"plugin": "image_folder", "config": {"path": str(folder)}}}
    if mode == "detect":
        body["prompts"] = {"set_inline": SET_INLINE}
    return body


def _run_body(folder):
    return {
        "ingest": {"plugin": "image_folder", "config": {"path": str(folder)}},
        "prompts": {"set_inline": SET_INLINE},
    }


def test_ciclo_basico(client, tmp_path):
    r = client.post("/api/preview", json=_preview_body(_images(tmp_path, n=200)))
    assert r.status_code == 201 and r.json()["preview_id"].startswith("pv_")
    assert client.get("/api/preview").json()["status"] == "streaming"
    assert client.delete("/api/preview").status_code == 204
    assert client.get("/api/preview").json()["status"] == "idle"
    assert client.delete("/api/preview").status_code == 204  # idempotente


def test_preview_409_si_run_activo(client, tmp_path):
    folder = _images(tmp_path, n=300)
    run = client.post("/api/runs", json=_run_body(folder))
    assert run.status_code == 201
    r = client.post("/api/preview", json=_preview_body(folder))
    assert r.status_code == 409
    body = r.json()
    assert body["reason"] == "run_active"
    assert body["active_run_id"] == run.json()["run_id"]
    client.post(f"/api/runs/{run.json()['run_id']}/stop")


def test_run_409_si_preview_activa(client, tmp_path):
    folder = _images(tmp_path, n=300)
    assert client.post("/api/preview", json=_preview_body(folder)).status_code == 201
    r = client.post("/api/runs", json=_run_body(folder))
    assert r.status_code == 409
    assert r.json()["reason"] == "preview_active"
    client.delete("/api/preview")


def test_preview_422_config_invalida(client, tmp_path):
    r = client.post("/api/preview", json=_preview_body(tmp_path / "no_existe"))
    assert r.status_code == 422


def test_ws_emite_frames_binarios(client, tmp_path):
    # F3 (flaky ~40%): con pocas imágenes chicas (64x48, n=500) la fuente
    # image_folder podía agotarse y cerrar la sesión de preview ANTES de que
    # el test llegara a abrir el WS (o a mitad de la primera recv), así el
    # cliente veía el mensaje de texto `state`/close 4404 en vez del primer
    # frame binario -> KeyError: 'bytes'. Fix test-only: conectar el WS
    # INMEDIATAMENTE después de crear la preview, en el mismo `with`, y usar
    # muchas más imágenes (2000, 640x480) para que la sesión siga viva el
    # tiempo suficiente sin volver el test vacuo (sigue exigiendo al menos un
    # frame binario válido).
    client.post("/api/preview", json=_preview_body(_images(tmp_path, n=2000, size=(640, 480))))
    with client.websocket_connect("/api/preview/stream") as ws:
        msg = ws.receive_bytes()
        hlen = struct.unpack(">I", msg[:4])[0]
        header = json.loads(msg[4 : 4 + hlen].decode("utf-8"))
        assert header["mode"] == "raw" and header["seq"] >= 1
        assert msg[4 + hlen : 6 + hlen] == b"\xff\xd8"
    client.delete("/api/preview")


def test_ws_sin_sesion_cierra_4404(client):
    with client.websocket_connect("/api/preview/stream") as ws:
        data = ws.receive()
        assert data["type"] == "websocket.close"
        assert data["code"] == 4404
