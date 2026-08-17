import json
import time
from types import SimpleNamespace

import pytest
from PIL import Image
from fastapi.testclient import TestClient

from eovrt_media.evaluation import runner
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


def _bench_run(tmp_path, run_id="run_b1", split="bench_v2_test"):
    run_dir = tmp_path / "runs" / run_id
    run_dir.mkdir(parents=True)
    (run_dir / "summary.json").write_text(
        json.dumps({"run_id": run_id, "status": "succeeded", "model_name": "mock"})
    )
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
    event = {
        "source": {"source_id": "img001.jpg"},
        "detections": [{"prompt_id": "person", "bbox_xyxy": [0, 0, 10, 10], "confidence": 0.9}],
    }
    (run_dir / "detections.jsonl").write_text(json.dumps(event) + "\n")
    return run_dir


def _patch_evaluator(tmp_path, monkeypatch):
    """El endpoint no pasa GT explícito: se apuntan los defaults del runner a
    fixtures y se reemplaza el evaluador por uno sintético."""
    script = tmp_path / "evaluate_bench.py"
    script.write_text("VALUE = 1\n")
    bench_coco = tmp_path / "bench.json"
    bench_coco.write_text("{}")
    person_gt = tmp_path / "person_gt.json"
    person_gt.write_text("{}")
    monkeypatch.setattr(runner, "EVALUATE_BENCH_SCRIPT", script)
    monkeypatch.setattr(runner, "DEFAULT_BENCH_COCO", bench_coco)
    monkeypatch.setattr(runner, "DEFAULT_PERSON_GT", person_gt)
    synthetic = SimpleNamespace(
        load_detections=lambda _p: {"img001.jpg": []},
        load_bench_coco=lambda _p: (
            {"img001.jpg": {"id": 1}},
            {1: [{"category_id": 1}]},
            {1: "person"},
        ),
        load_person_gt=lambda _p: [],
        evaluate_class=lambda cls, *_a: {"class": cls, "AP50": 0.8, "n_gt": 1, "n_det": 1},
        evaluate_cr01=lambda *_a: {"cr01_recall": 0.5},
    )
    monkeypatch.setattr(runner, "_load_evaluate_bench", lambda: synthetic)


def test_post_evaluate_ok_enriquecido_y_atomico(client, tmp_path, monkeypatch):
    run_dir = _bench_run(tmp_path)
    _patch_evaluator(tmp_path, monkeypatch)

    r = client.post("/api/runs/run_b1/evaluate")

    assert r.status_code == 200
    body = r.json()
    assert body["type"] == "perception"
    assert body["mAP50"] == 0.8
    assert body["model"] == "mock"
    assert body["bench_split"] == "bench_v2_test"
    assert body["cr01_detection_recall"] == 0.5
    # persistencia atómica y enriquecida
    assert list(run_dir.glob("*.tmp")) == []
    on_disk = json.loads((run_dir / "eval_perception.json").read_text())
    assert on_disk["mAP50"] == 0.8
    # el flag del run refleja la evaluación
    assert client.get("/api/runs/run_b1").json()["evaluated"] is True


def test_post_evaluate_no_bench_422(client, tmp_path):
    _bench_run(tmp_path, run_id="run_demo", split="demo_v2")
    r = client.post("/api/runs/run_demo/evaluate")
    assert r.status_code == 422
    assert "BENCH" in r.json()["detail"]


def test_post_evaluate_run_en_curso_409(client, tmp_path):
    folder = tmp_path / "imgs"
    folder.mkdir()
    for i in range(400):
        Image.new("RGB", (64, 48), (1, 2, 3)).save(folder / f"i{i:03d}.png")
    body = {
        "ingest": {"plugin": "image_folder", "config": {"path": str(folder)}},
        "prompts": {"set_inline": SET_INLINE},
        "run": {},
    }
    run_id = client.post("/api/runs", json=body).json()["run_id"]
    r = client.post(f"/api/runs/{run_id}/evaluate")
    assert r.status_code == 409
    client.post(f"/api/runs/{run_id}/stop")
    deadline = time.monotonic() + 15.0
    while time.monotonic() < deadline:
        if client.get(f"/api/runs/{run_id}").json()["status"] != "running":
            break
        time.sleep(0.05)


def test_post_evaluate_404_desconocido_e_invalido(client):
    assert client.post("/api/runs/nope/evaluate").status_code == 404
    assert client.post("/api/runs/%2e%2e/evaluate").status_code == 404


def test_post_evaluate_gt_ausente_422_accionable(client, tmp_path, monkeypatch):
    _bench_run(tmp_path)
    monkeypatch.setattr(runner, "EVALUATE_BENCH_SCRIPT", tmp_path / "no_existe.py")
    r = client.post("/api/runs/run_b1/evaluate")
    assert r.status_code == 422
    assert "e-ovrt_datasets" in r.json()["detail"]


def test_mean_ap50():
    from eovrt_media.evaluation.schemas import ClassResult
    from eovrt_media.evaluation.runner import _mean_ap50

    rows = [
        ClassResult(class_name="person", AP50=0.8, n_gt=2, n_det=2),
        ClassResult(class_name="helmet", AP50=None, n_gt=0, n_det=1),
        ClassResult(class_name="bare_head", AP50=0.0, n_gt=1, n_det=0),
    ]
    assert _mean_ap50(rows) == 0.4
    assert _mean_ap50([ClassResult(class_name="x", AP50=None, n_gt=0, n_det=0)]) is None


def test_settings_eval_iou_threshold():
    base = {"EOVRT_MODEL_REF": "mock"}
    assert ServiceSettings.from_env(base).eval_iou_threshold == 0.5
    assert (
        ServiceSettings.from_env({**base, "EOVRT_EVAL_IOU_THRESHOLD": "0.4"}).eval_iou_threshold
        == 0.4
    )


def test_get_evaluate_404_si_no_evaluado(client, tmp_path):
    _bench_run(tmp_path)
    assert client.get("/api/runs/run_b1/evaluate").status_code == 404


def test_get_evaluate_devuelve_lo_persistido(client, tmp_path, monkeypatch):
    _bench_run(tmp_path)
    _patch_evaluator(tmp_path, monkeypatch)
    posted = client.post("/api/runs/run_b1/evaluate").json()

    got = client.get("/api/runs/run_b1/evaluate")

    assert got.status_code == 200
    assert got.json() == posted


def test_get_evaluate_corrupto_es_404(client, tmp_path):
    run_dir = _bench_run(tmp_path)
    (run_dir / "eval_perception.json").write_text('{"mAP50": 0.4')
    assert client.get("/api/runs/run_b1/evaluate").status_code == 404


def test_get_evaluate_run_id_invalido_404(client):
    assert client.get("/api/runs/%2e%2e/evaluate").status_code == 404
