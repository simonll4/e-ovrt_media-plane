import json

import pytest
from fastapi.testclient import TestClient

from eovrt_media.service.app import create_app
from eovrt_media.service.settings import ServiceSettings


@pytest.fixture()
def client(tmp_path):
    settings = ServiceSettings.from_env(
        {"EOVRT_MODEL_REF": "mock", "EOVRT_RUNS_DIR": str(tmp_path / "runs")}
    )
    with TestClient(create_app(settings)) as c:
        yield c


def _finished_run(tmp_path, run_id="run_b1", split="bench_v2_test", provenance=True):
    run_dir = tmp_path / "runs" / run_id
    run_dir.mkdir(parents=True)
    (run_dir / "summary.json").write_text(
        json.dumps({"run_id": run_id, "status": "succeeded", "model_name": "mock"})
    )
    if provenance:
        (run_dir / "run_provenance.json").write_text(
            json.dumps(
                {
                    "run_id": run_id,
                    "dataset_id": "construction_site_safety",
                    "view": "canonical_v2",
                    "split": split,
                }
            )
        )
    return run_dir


def test_get_run_bench_expone_split_y_no_evaluado(client, tmp_path):
    _finished_run(tmp_path)
    body = client.get("/api/runs/run_b1").json()
    assert body["bench_split"] == "bench_v2_test"
    assert body["evaluated"] is False


def test_get_run_evaluado_true_si_existe_eval_json(client, tmp_path):
    run_dir = _finished_run(tmp_path)
    (run_dir / "eval_perception.json").write_text("{}")
    body = client.get("/api/runs/run_b1").json()
    assert body["evaluated"] is True


def test_get_run_split_no_bench_es_null(client, tmp_path):
    _finished_run(tmp_path, run_id="run_demo", split="demo_v2")
    body = client.get("/api/runs/run_demo").json()
    assert body["bench_split"] is None


def test_get_run_sin_provenance_es_null(client, tmp_path):
    _finished_run(tmp_path, run_id="run_sin_prov", provenance=False)
    body = client.get("/api/runs/run_sin_prov").json()
    assert body["bench_split"] is None
    assert body["evaluated"] is False


def test_get_run_provenance_corrupta_no_rompe(client, tmp_path):
    run_dir = _finished_run(tmp_path, run_id="run_corrupto", provenance=False)
    (run_dir / "run_provenance.json").write_text('{"split": "bench_v2')
    r = client.get("/api/runs/run_corrupto")
    assert r.status_code == 200
    assert r.json()["bench_split"] is None


def test_list_runs_incluye_flags(client, tmp_path):
    _finished_run(tmp_path)
    _finished_run(tmp_path, run_id="run_demo", split="demo_v2")
    rows = {row["run_id"]: row for row in client.get("/api/runs").json()}
    assert rows["run_b1"]["bench_split"] == "bench_v2_test"
    assert rows["run_b1"]["evaluated"] is False
    assert rows["run_demo"]["bench_split"] is None
