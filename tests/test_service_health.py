from fastapi.testclient import TestClient
from eovrt_media.service.app import create_app
from eovrt_media.service.settings import ServiceSettings


def _app():
    return create_app(ServiceSettings.from_env({"EOVRT_MODEL_REF": "mock"}))


def test_healthz_ok():
    with TestClient(_app()) as client:
        r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_readyz_503_sin_modelo():
    # En esta task el lifespan aún no carga modelo: not ready.
    # (Task 11 reemplaza este test por la variante con carga real.)
    with TestClient(_app()) as client:
        r = client.get("/readyz")
    assert r.status_code == 503
