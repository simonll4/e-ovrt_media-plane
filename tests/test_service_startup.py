import json

from fastapi.testclient import TestClient
from eovrt_media.service.app import create_app
from eovrt_media.service.settings import ServiceSettings


def _settings(tmp_path, model_ref="mock"):
    return ServiceSettings.from_env(
        {"EOVRT_MODEL_REF": model_ref, "EOVRT_RUNS_DIR": str(tmp_path / "runs")}
    )


def test_startup_carga_modelo_y_ready(tmp_path):
    with TestClient(create_app(_settings(tmp_path))) as client:
        r = client.get("/readyz")
        assert r.status_code == 200
        assert r.json()["model"] == "mock"
        m = client.get("/api/model").json()
        assert (m["adapter"] or m["name"]) == "mock"
        assert "thresholds" in m and "device" in m


def test_startup_modelo_invalido_no_ready(tmp_path):
    with TestClient(create_app(_settings(tmp_path, model_ref="no/existe"))) as client:
        r = client.get("/readyz")
        assert r.status_code == 503
        assert r.json()["error"]
        assert client.get("/healthz").status_code == 200  # proceso vivo igual


def test_reconciliacion_huerfano_al_startup(tmp_path):
    """Un run dir sin summary.json (kill/OOM antes de F1's _finalize) debe
    quedar visible via la API tras un reinicio del servicio, marcado como
    'interrupted', en vez de desaparecer silenciosamente."""
    runs_dir = tmp_path / "runs"
    huerfano = runs_dir / "run_huerfano"
    huerfano.mkdir(parents=True)
    (huerfano / "detections.jsonl").write_text('{"unit_id": "u1"}\n')

    ok = runs_dir / "run_ok"
    ok.mkdir(parents=True)
    (ok / "summary.json").write_text('{"run_id": "run_ok", "status": "succeeded"}')

    with TestClient(create_app(_settings(tmp_path))) as client:
        listado = client.get("/api/runs").json()
        by_id = {item["run_id"]: item for item in listado}

        assert "run_huerfano" in by_id
        assert by_id["run_huerfano"]["status"] == "interrupted"

        detalle = client.get("/api/runs/run_huerfano").json()
        assert detalle["summary"]["status"] == "interrupted"

        # Idempotencia: el run que ya tenía summary válido no se pisa.
        assert by_id["run_ok"]["status"] == "succeeded"
        summary_ok = json.loads((ok / "summary.json").read_text())
        assert summary_ok == {"run_id": "run_ok", "status": "succeeded"}
