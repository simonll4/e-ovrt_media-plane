import json
import pytest
from fastapi.testclient import TestClient
from eovrt_media.service.app import create_app
from eovrt_media.service.settings import ServiceSettings


@pytest.fixture()
def client_y_run(tmp_path):
    runs = tmp_path / "runs"
    run_dir = runs / "run_x"
    run_dir.mkdir(parents=True)
    detections = [{"unit_id": f"u{i}", "detections": []} for i in range(25)]
    (run_dir / "detections.jsonl").write_text(
        "\n".join(json.dumps(d) for d in detections) + "\n"
    )
    (run_dir / "summary.json").write_text(json.dumps({"run_id": "run_x", "status": "succeeded"}))
    (run_dir / "annotated.mp4").write_bytes(b"0123456789abcdef")
    settings = ServiceSettings.from_env(
        {"EOVRT_MODEL_REF": "mock", "EOVRT_RUNS_DIR": str(runs)}
    )
    with TestClient(create_app(settings)) as c:
        yield c


def test_detections_paginadas(client_y_run):
    r = client_y_run.get("/api/runs/run_x/detections?page=2&page_size=10")
    assert r.status_code == 200
    data = r.json()
    assert data["total"] == 25
    assert len(data["items"]) == 10
    assert data["items"][0]["unit_id"] == "u10"


def test_artifact_con_range(client_y_run):
    r = client_y_run.get(
        "/api/runs/run_x/artifacts/annotated.mp4", headers={"Range": "bytes=0-3"}
    )
    assert r.status_code == 206
    assert r.content == b"0123"


def test_artifact_traversal_404(client_y_run):
    r = client_y_run.get("/api/runs/run_x/artifacts/..%2F..%2Fetc%2Fpasswd")
    assert r.status_code == 404


def test_artifact_inexistente_404(client_y_run):
    assert client_y_run.get("/api/runs/run_x/artifacts/nada.bin").status_code == 404
