import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from eovrt_media.cli import app
from eovrt_media.evaluation import ClassResult, EvalPerceptionResults, runner
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


def _synthetic_evaluator() -> SimpleNamespace:
    def evaluate_class(
        class_name: str,
        _detections_by_img: dict[str, list[dict]],
        _images_by_filename: dict[str, dict],
        _gt_by_image_id: dict[int, list[dict]],
        _cat_by_id: dict[int, str],
        _iou_threshold: float,
    ) -> dict[str, str | float | int]:
        results = {
            "person": {"class": "person", "AP50": 1.0, "n_gt": 2, "n_det": 2},
            "helmet": {"class": "helmet", "AP50": 1.0, "n_gt": 1, "n_det": 1},
        }
        return results[class_name]

    return SimpleNamespace(
        load_detections=lambda _paths: {"img001.jpg": [], "img002.jpg": []},
        load_bench_coco=lambda _path: (
            {"img001.jpg": {"id": 1}, "img002.jpg": {"id": 2}},
            {},
            {1: "person", 2: "helmet"},
        ),
        load_person_gt=lambda _path: [],
        evaluate_class=evaluate_class,
        evaluate_cr01=lambda *_args: {"cr01_recall": 0.5},
    )


def test_run_evaluation_returns_perception_results(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_dir = tmp_path / "run_001"
    run_dir.mkdir()
    _write_detections(run_dir)
    bench_coco, person_gt = _write_benchmark(tmp_path)
    monkeypatch.setattr(runner, "_load_evaluate_bench", _synthetic_evaluator)

    result = run_evaluation(run_dir, bench_coco=bench_coco, person_gt=person_gt)

    assert result.type == "perception"
    assert result.run_id == "run_001"
    assert len(result.per_class) == 2
    assert [(item.class_name, item.n_gt, item.n_det) for item in result.per_class] == [
        ("person", 2, 2),
        ("helmet", 1, 1),
    ]
    assert result.cr01_detection_recall == 0.5


def test_run_evaluation_writes_json(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_dir = tmp_path / "run_002"
    run_dir.mkdir()
    _write_detections(run_dir)
    bench_coco, person_gt = _write_benchmark(tmp_path)
    monkeypatch.setattr(runner, "_load_evaluate_bench", _synthetic_evaluator)

    run_evaluation(run_dir, bench_coco=bench_coco, person_gt=person_gt)

    payload = json.loads((run_dir / "eval_perception.json").read_text())
    assert payload["type"] == "perception"
    assert [(item["class_name"], item["n_gt"], item["n_det"]) for item in payload["per_class"]] == [
        ("person", 2, 2),
        ("helmet", 1, 1),
    ]
    assert payload["cr01_detection_recall"] == 0.5


def test_evaluate_command_writes_artifact_and_displays_per_class_results(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_dir = tmp_path / "run_006"
    run_dir.mkdir()
    _write_detections(run_dir)
    bench_coco, person_gt = _write_benchmark(tmp_path)
    monkeypatch.setattr(runner, "_load_evaluate_bench", _synthetic_evaluator)

    result = CliRunner().invoke(
        app,
        [
            "evaluate",
            "--run",
            str(run_dir),
            "--bench-coco",
            str(bench_coco),
            "--person-gt",
            str(person_gt),
        ],
    )

    assert result.exit_code == 0, result.output
    assert (run_dir / "eval_perception.json").exists()
    assert "AP" in result.output or "person" in result.output


def test_run_evaluation_missing_detections_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_dir = tmp_path / "run_003"
    run_dir.mkdir()
    bench_coco, person_gt = _write_benchmark(tmp_path)
    monkeypatch.setattr(runner, "_load_evaluate_bench", _synthetic_evaluator)

    with pytest.raises(FileNotFoundError, match="detections.jsonl"):
        run_evaluation(run_dir, bench_coco=bench_coco, person_gt=person_gt)


def test_auto_discover_missing_sibling_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    run_dir = tmp_path / "run_004"
    run_dir.mkdir()
    _write_detections(run_dir)
    monkeypatch.chdir(tmp_path)

    with pytest.raises(FileNotFoundError, match="e-ovrt_datasets"):
        run_evaluation(run_dir)


@pytest.mark.parametrize(
    ("bench_coco_arg", "person_gt_arg"),
    [(None, "explicit_person_gt"), ("explicit_bench_coco", None), (None, None)],
)
def test_resolve_bench_paths_validates_sibling_without_loading(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    bench_coco_arg: str | None,
    person_gt_arg: str | None,
) -> None:
    script_path = tmp_path / "evaluate_bench.py"
    script_path.write_text("VALUE = 1\n")
    bench_coco, person_gt = _write_benchmark(tmp_path)
    monkeypatch.setattr(runner, "EVALUATE_BENCH_SCRIPT", script_path)
    monkeypatch.setattr(runner, "DEFAULT_BENCH_COCO", bench_coco)
    monkeypatch.setattr(runner, "DEFAULT_PERSON_GT", person_gt)

    def fail_if_loaded() -> SimpleNamespace:
        raise AssertionError("path resolution must not load the evaluator")

    monkeypatch.setattr(runner, "_load_evaluate_bench", fail_if_loaded)
    resolved_bench, resolved_person_gt = runner._resolve_bench_paths(
        bench_coco if bench_coco_arg else None,
        person_gt if person_gt_arg else None,
    )

    assert resolved_bench == bench_coco.resolve()
    assert resolved_person_gt == person_gt.resolve()


def test_run_evaluation_loads_evaluator_once_after_path_validation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_dir = tmp_path / "run_005"
    run_dir.mkdir()
    _write_detections(run_dir)
    bench_coco, person_gt = _write_benchmark(tmp_path)
    calls = 0
    script_path = tmp_path / "evaluate_bench.py"
    script_path.write_text("VALUE = 1\n")

    def load_evaluator() -> SimpleNamespace:
        nonlocal calls
        calls += 1
        return _synthetic_evaluator()

    monkeypatch.setattr(runner, "DEFAULT_BENCH_COCO", bench_coco)
    monkeypatch.setattr(runner, "EVALUATE_BENCH_SCRIPT", script_path)
    monkeypatch.setattr(runner, "_load_evaluate_bench", load_evaluator)

    run_evaluation(run_dir, person_gt=person_gt)

    assert calls == 1


def test_load_evaluate_bench_loads_and_caches_temporary_script(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    script_path = tmp_path / "evaluate_bench.py"
    script_path.write_text("def evaluator_marker():\n    return 'loaded'\n")
    monkeypatch.setattr(runner, "EVALUATE_BENCH_SCRIPT", script_path)

    first = runner._load_evaluate_bench()
    second = runner._load_evaluate_bench()

    assert first is second
    assert first.__name__ == "eovrt_media._evaluate_bench_sibling"
    assert first.evaluator_marker() == "loaded"
