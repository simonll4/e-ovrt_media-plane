import json
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


def test_ingest_plugin_no_disponible_es_4xx(client, tmp_path):
    # oak_d está en el registro pero available:false. Antes escapaba como 500
    # (NotImplementedError del loader); ahora es un 4xx claro y no un 500.
    body = _body(_images(tmp_path))
    body["ingest"]["plugin"] = "oak_d"
    r = client.post("/api/runs", json=body)
    assert 400 <= r.status_code < 500
    assert r.status_code != 500
    assert "oak_d" in r.json()["detail"]


def test_detections_run_id_con_path_traversal_es_404(client):
    # Un run_id con '..' no debe poder reubicar el run_dir: se rechaza como 404.
    r = client.get("/api/runs/..%2F..%2Fetc/detections")
    assert r.status_code == 404
    r2 = client.get("/api/runs/bad..id/detections")
    assert r2.status_code == 404


def test_artifact_run_id_con_path_traversal_es_404(client):
    r = client.get("/api/runs/bad..id/artifacts/errors.jsonl")
    assert r.status_code == 404


def test_summary_escrito_atomico(client, tmp_path):
    # Ancla Fix 1: la escritura de summary.json debe ser atómica (tmp + os.replace),
    # así que al terminar la corrida no debe quedar ningún *.tmp huérfano y el
    # summary.json final debe ser JSON válido y completo.
    run_id = client.post("/api/runs", json=_body(_images(tmp_path))).json()["run_id"]
    assert _wait_final(client, run_id) == "succeeded"
    run_dir = tmp_path / "runs" / run_id
    assert list(run_dir.glob("*.tmp")) == []
    summary = json.loads((run_dir / "summary.json").read_text())
    assert summary["status"] == "succeeded"


def test_experiment_id_llega_al_summary_end_to_end(client, tmp_path):
    # Spec 42 §4.1: experiment_id viaja request -> raw config -> RunConfig.experiment.id
    # -> RunArtifactWriter (run_artifact_writer.py:212) -> summary.json.
    body = _body(_images(tmp_path))
    body["experiment_id"] = "exp-e2e"
    run_id = client.post("/api/runs", json=body).json()["run_id"]
    assert _wait_final(client, run_id) == "succeeded"
    run_dir = tmp_path / "runs" / run_id
    summary = json.loads((run_dir / "summary.json").read_text())
    assert summary["experiment_id"] == "exp-e2e"


def test_list_runs_summary_corrupto_no_rompe(client, tmp_path):
    # Ancla Fix 2/3: un summary.json truncado/corrupto (kill/OOM a mitad de
    # escritura, o borrado a mitad de lectura) no debe tumbar el listado
    # completo con un 500; el run corrupto simplemente se omite.
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir(parents=True, exist_ok=True)
    corrupt_dir = runs_dir / "run_corrupto"
    corrupt_dir.mkdir()
    (corrupt_dir / "summary.json").write_text('{"run_id": "run_corrupto", "status": "s')

    ok_run_id = client.post("/api/runs", json=_body(_images(tmp_path))).json()["run_id"]
    assert _wait_final(client, ok_run_id) == "succeeded"

    r = client.get("/api/runs")
    assert r.status_code == 200
    run_ids = [item["run_id"] for item in r.json()]
    assert "run_corrupto" not in run_ids
    assert ok_run_id in run_ids


def test_get_run_summary_corrupto_404(client, tmp_path):
    # Ancla Fix 2: GET de un run individual con summary ilegible debe dar 404,
    # no 500.
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir(parents=True, exist_ok=True)
    corrupt_dir = runs_dir / "run_corrupto"
    corrupt_dir.mkdir()
    (corrupt_dir / "summary.json").write_text("{esto no es json valido")

    r = client.get("/api/runs/run_corrupto")
    assert r.status_code == 404


def test_run_id_invalido_es_404_en_get_stop_delete(client):
    # NOTA (review, Fix C): los casos originales de este test parametrizado
    # ("..%2F..%2Fetc" y "bad..id") daban 404 aun SIN _require_valid_run_id,
    # así que no anclaban el fix:
    #   - "..%2F..%2Fetc" contiene un '/' codificado: el router de Starlette
    #     ya lo rechaza (no matchea el patrón de {run_id}, que no acepta '/')
    #     antes de que el validador entre en juego.
    #   - "bad..id" es un nombre de directorio literal que simplemente no
    #     existe bajo runs_dir: manager.get()/manager.stop() ya devuelven
    #     UnknownRunError -> 404 sin necesidad del validador.
    # El único run_id que discrimina de verdad es "%2e%2e" (decodifica a
    # ".."): sin el validador, manager.get("..") arma runs_dir/../summary.json
    # y puede leer/filtrar un summary.json fuera de runs_dir en vez de dar 404
    # (ver test_run_id_dotdot_no_permite_traversal_real, que ancla esto por
    # revert con un archivo fuera de runs_dir y verifica que no se filtra).
    # stop_run no construye ninguna ruta de filesystem a partir de run_id
    # (sólo compara contra el run_id del run activo en memoria bajo lock), así
    # que ningún run_id puede discriminar el fix ahí — se deja como chequeo de
    # consistencia/defensa-en-profundidad (incluye el validador igual que
    # get/delete), no como ancla.
    bad_run_id = "%2e%2e"
    assert client.get(f"/api/runs/{bad_run_id}").status_code == 404
    assert client.post(f"/api/runs/{bad_run_id}/stop").status_code == 404
    assert client.delete(f"/api/runs/{bad_run_id}").status_code == 404


def test_run_id_dotdot_no_permite_traversal_real(client, tmp_path):
    # Prueba de explotación real (no sólo un 404 incidental): sin
    # _require_valid_run_id, run_id=".." resuelve runs_dir/../summary.json,
    # es decir un archivo *fuera* de runs_dir. Usamos %2e%2e (no ".." literal)
    # porque el cliente HTTP normaliza ".." en la URL antes de enviarla, lo que
    # enmascararía el bug con un 404 de "ruta no encontrada" ajeno al fix.
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir(parents=True, exist_ok=True)
    outside_summary = tmp_path / "summary.json"
    outside_summary.write_text(json.dumps({"status": "leaked"}))

    r = client.get("/api/runs/%2e%2e")
    assert r.status_code == 404

    r2 = client.delete("/api/runs/%2e%2e")
    assert r2.status_code == 404
    # El archivo fuera de runs_dir no debe haber sido leído ni borrado.
    assert outside_summary.exists()
    assert json.loads(outside_summary.read_text())["status"] == "leaked"
