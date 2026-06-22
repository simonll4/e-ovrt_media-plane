import json
from pathlib import Path

import pytest

from eovrt_media.evaluation import ClassResult, EvalPerceptionResults
from eovrt_media.evaluation.runner import run_evaluation


def test_class_result_fields(tmp_path: Path) -> None:
    result = ClassResult(class_name="person", AP50=0.812, n_gt=10, n_det=11)

    assert result.class_name == "person"
    assert result.AP50 == 0.812
    assert result.n_gt == 10
    assert result.n_det == 11


def test_eval_perception_results_type_literal() -> None:
    result = EvalPerceptionResults(
        run_id="run_001",
        benchmark="bench_test",
        iou_threshold=0.5,
        per_class=[ClassResult(class_name="person", AP50=0.8, n_gt=5, n_det=5)],
        cr01_detection_recall=0.7,
        evaluated_at="2026-06-21T22:00:00Z",
    )

    assert result.type == "perception"


def test_eval_perception_results_json_roundtrip() -> None:
    result = EvalPerceptionResults(
        run_id="run_001",
        benchmark="bench_test",
        iou_threshold=0.5,
        per_class=[
            ClassResult(class_name="person", AP50=0.812, n_gt=10, n_det=11),
            ClassResult(class_name="helmet", AP50=None, n_gt=0, n_det=3),
        ],
        cr01_detection_recall=None,
        evaluated_at="2026-06-21T22:00:00Z",
    )

    payload = json.loads(result.model_dump_json())

    assert payload["type"] == "perception"
    assert payload["per_class"][0]["class_name"] == "person"
    assert payload["per_class"][1]["AP50"] is None
    assert payload["cr01_detection_recall"] is None


def _write_detections(run_dir: Path) -> None:
    events = [
        {
            "source": {"source_id": "img001.jpg"},
            "detections": [
                {
                    "prompt_id": "person",
                    "bbox_xyxy": [10, 10, 100, 200],
                    "confidence": 0.9,
                },
                {
                    "prompt_id": "helmet",
                    "bbox_xyxy": [20, 10, 60, 40],
                    "confidence": 0.85,
                },
            ],
        },
        {
            "source": {"source_id": "img002.jpg"},
            "detections": [
                {
                    "prompt_id": "person",
                    "bbox_xyxy": [5, 5, 80, 180],
                    "confidence": 0.75,
                },
            ],
        },
    ]
    (run_dir / "detections.jsonl").write_text(
        "\n".join(json.dumps(event) for event in events) + "\n"
    )


def _write_benchmark(tmp_path: Path) -> tuple[Path, Path]:
    bench_coco = tmp_path / "construction_site_safety_bench.json"
    bench_coco.write_text(
        json.dumps(
            {
                "images": [
                    {
                        "id": 1,
                        "file_name": "/data/img001.jpg",
                        "width": 640,
                        "height": 480,
                    },
                    {
                        "id": 2,
                        "file_name": "/data/img002.jpg",
                        "width": 640,
                        "height": 480,
                    },
                ],
                "categories": [
                    {"id": 1, "name": "person"},
                    {"id": 2, "name": "helmet"},
                ],
                "annotations": [
                    {"id": 1, "image_id": 1, "category_id": 1, "bbox": [10, 10, 90, 190]},
                    {"id": 2, "image_id": 1, "category_id": 2, "bbox": [20, 10, 40, 30]},
                    {"id": 3, "image_id": 2, "category_id": 1, "bbox": [5, 5, 75, 175]},
                ],
            }
        )
    )
    person_gt = tmp_path / "person_gt.json"
    person_gt.write_text(
        json.dumps(
            {
                "records": [
                    {
                        "file_name": "/data/img002.jpg",
                        "has_helmet": False,
                        "person_bbox": [5, 5, 80, 180],
                    }
                ]
            }
        )
    )
    return bench_coco, person_gt


def test_run_evaluation_returns_perception_results(tmp_path: Path) -> None:
    run_dir = tmp_path / "run_001"
    run_dir.mkdir()
    _write_detections(run_dir)
    bench_coco, person_gt = _write_benchmark(tmp_path)

    result = run_evaluation(run_dir, bench_coco=bench_coco, person_gt=person_gt)

    assert result.type == "perception"
    assert result.run_id == "run_001"
    assert len(result.per_class) == 2
    assert [item.class_name for item in result.per_class] == ["person", "helmet"]


def test_run_evaluation_writes_json(tmp_path: Path) -> None:
    run_dir = tmp_path / "run_002"
    run_dir.mkdir()
    _write_detections(run_dir)
    bench_coco, person_gt = _write_benchmark(tmp_path)

    run_evaluation(run_dir, bench_coco=bench_coco, person_gt=person_gt)

    payload = json.loads((run_dir / "eval_perception.json").read_text())
    assert payload["type"] == "perception"
    assert "per_class" in payload
    assert "cr01_detection_recall" in payload


def test_run_evaluation_missing_detections_raises(tmp_path: Path) -> None:
    run_dir = tmp_path / "run_003"
    run_dir.mkdir()
    bench_coco, person_gt = _write_benchmark(tmp_path)

    with pytest.raises(FileNotFoundError, match="detections.jsonl"):
        run_evaluation(run_dir, bench_coco=bench_coco, person_gt=person_gt)


def test_auto_discover_missing_sibling_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    run_dir = tmp_path / "run_004"
    run_dir.mkdir()
    _write_detections(run_dir)
    monkeypatch.chdir(tmp_path)

    with pytest.raises(FileNotFoundError, match="e-ovrt_datasets"):
        run_evaluation(run_dir)
