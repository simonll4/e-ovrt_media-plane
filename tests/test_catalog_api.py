import pytest
import yaml
from fastapi.testclient import TestClient
from eovrt_media.service.app import create_app
from eovrt_media.service.settings import ServiceSettings


@pytest.fixture()
def client(tmp_path):
    # catálogo propio del test para no depender de los datasets reales
    catalog = tmp_path / "configs"
    (catalog / "datasets").mkdir(parents=True)
    (catalog / "models").mkdir()
    (catalog / "models" / "mock.yaml").write_text(yaml.safe_dump({"adapter": "mock"}))
    existing = tmp_path / "data"
    existing.mkdir()
    (catalog / "datasets" / "demo.yaml").write_text(
        yaml.safe_dump({"type": "image_folder", "path": str(existing), "description": "demo"})
    )
    (catalog / "datasets" / "roto.yaml").write_text(
        yaml.safe_dump({"type": "image_folder", "path": "/no/existe"})
    )
    settings = ServiceSettings.from_env({
        "EOVRT_MODEL_REF": "mock",
        "EOVRT_RUNS_DIR": str(tmp_path / "runs"),
        "EOVRT_MEDIA_CATALOG_ROOT": str(catalog),
    })
    with TestClient(create_app(settings)) as c:
        yield c


def test_ingest_plugins(client):
    plugins = {p["id"]: p for p in client.get("/api/catalog/ingest-plugins").json()}
    assert plugins["oak_d"]["available"] is False
    assert plugins["image_folder"]["kind"] == "bounded"


def test_datasets_con_disponibilidad(client):
    datasets = {d["id"]: d for d in client.get("/api/catalog/datasets").json()}
    assert datasets["demo"]["available"] is True
    assert datasets["roto"]["available"] is False


def test_datasets_omite_yaml_malformado(client, tmp_path):
    # un archivo YAML corrupto en el catálogo no debe tumbar el endpoint completo
    catalog_root = client.app.state.settings.catalog_root
    (catalog_root / "datasets" / "corrupto.yaml").write_text("key: [unclosed")

    response = client.get("/api/catalog/datasets")

    assert response.status_code == 200
    datasets = {d["id"]: d for d in response.json()}
    assert "corrupto" not in datasets
    assert datasets["demo"]["available"] is True
