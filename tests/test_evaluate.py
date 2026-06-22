import json
from pathlib import Path

from eovrt_media.evaluation import ClassResult, EvalPerceptionResults


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
