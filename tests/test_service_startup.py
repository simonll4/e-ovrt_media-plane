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
