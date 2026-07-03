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


def test_readyz_503_con_modelo_invalido():
    from eovrt_media.service.settings import ServiceSettings
    settings = ServiceSettings.from_env({"EOVRT_MODEL_REF": "no/existe"})
    with TestClient(create_app(settings)) as client:
        assert client.get("/readyz").status_code == 503
