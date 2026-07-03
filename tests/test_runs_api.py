import time
import pytest
from PIL import Image
from fastapi.testclient import TestClient
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


def _images(tmp_path, n=3):
    folder = tmp_path / "imgs"
    folder.mkdir(exist_ok=True)
    for i in range(n):
        Image.new("RGB", (64, 48), (1, 2, 3)).save(folder / f"i{i:03d}.png")
    return folder


def _body(folder, **run):
    return {
        "ingest": {"plugin": "image_folder", "config": {"path": str(folder)}},
        "prompts": {"set_inline": SET_INLINE},
        "run": run,
    }


def _wait_final(client, run_id, timeout=15.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        status = client.get(f"/api/runs/{run_id}").json()["status"]
        if status != "running":
            return status
        time.sleep(0.05)
    raise AssertionError("run no terminó")


def test_ciclo_completo(client, tmp_path):
    r = client.post("/api/runs", json=_body(_images(tmp_path)))
    assert r.status_code == 201
    run_id = r.json()["run_id"]
    assert _wait_final(client, run_id) == "succeeded"
    listado = client.get("/api/runs").json()
    assert any(item["run_id"] == run_id for item in listado)


def test_seccion_model_es_422(client, tmp_path):
    body = _body(_images(tmp_path))
    body["model"] = {"ref": "yoloe/yoloe-26s"}
    assert client.post("/api/runs", json=body).status_code == 422


def test_busy_409_y_stop(client, tmp_path):
    folder = _images(tmp_path, n=400)
    run_id = client.post("/api/runs", json=_body(folder)).json()["run_id"]
    r = client.post("/api/runs", json=_body(folder))
    assert r.status_code == 409
    assert r.json()["active_run_id"] == run_id
    assert client.post(f"/api/runs/{run_id}/stop").status_code == 202
    assert _wait_final(client, run_id) == "stopped"


def test_delete_run_terminado(client, tmp_path):
    run_id = client.post("/api/runs", json=_body(_images(tmp_path))).json()["run_id"]
    _wait_final(client, run_id)
    assert client.delete(f"/api/runs/{run_id}").status_code == 204
    assert client.get(f"/api/runs/{run_id}").status_code == 404


def test_404_desconocido(client):
    assert client.get("/api/runs/nope").status_code == 404


def test_ready_gate_503_en_todos_los_endpoints(tmp_path):
    # Modelo inválido -> app.state.ready queda False (mismo patrón que
    # test_service_startup.py::test_startup_modelo_invalido_no_ready).
    settings = ServiceSettings.from_env(
        {"EOVRT_MODEL_REF": "no/existe", "EOVRT_RUNS_DIR": str(tmp_path / "runs")}
    )
    with TestClient(create_app(settings)) as client:
        body = _body(_images(tmp_path))
        assert client.post("/api/runs", json=body).status_code == 503
        assert client.get("/api/runs").status_code == 503
        assert client.get("/api/runs/any-id").status_code == 503
        assert client.post("/api/runs/any-id/stop").status_code == 503
        assert client.delete("/api/runs/any-id").status_code == 503


def test_stop_404_desconocido(client):
    assert client.post("/api/runs/nope/stop").status_code == 404


def test_delete_404_desconocido(client):
    assert client.delete("/api/runs/nope").status_code == 404


def test_delete_409_run_activo(client, tmp_path):
    folder = _images(tmp_path, n=400)
    run_id = client.post("/api/runs", json=_body(folder)).json()["run_id"]
    assert client.delete(f"/api/runs/{run_id}").status_code == 409
    assert client.post(f"/api/runs/{run_id}/stop").status_code == 202
    assert _wait_final(client, run_id) == "stopped"


def test_ingest_plugin_desconocido_es_422(client, tmp_path):
    # IngestSpec.plugin es un str libre (no Literal/enum), por lo que un plugin
    # inexistente pasa la validación de Pydantic y sólo falla dentro de
    # RunManager.start_run -> to_raw_run_config, que levanta ValueError.
    # Eso ejerce el propio try/except ValueError -> 422 del router (no el 422
    # genérico de FastAPI por body mal formado).
    body = _body(_images(tmp_path))
    body["ingest"]["plugin"] = "plugin_inexistente"
    r = client.post("/api/runs", json=body)
    assert r.status_code == 422
    assert "plugin_inexistente" in r.json()["detail"]
