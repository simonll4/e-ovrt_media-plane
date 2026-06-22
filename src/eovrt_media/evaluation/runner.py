from __future__ import annotations

import importlib.util
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import ModuleType

from .schemas import ClassResult, EvalPerceptionResults


EVALUATE_BENCH_SCRIPT = Path(
    "../e-ovrt_datasets/datasets/scripts/bench/evaluate_bench.py"
)
DEFAULT_BENCH_COCO = Path(
    "../e-ovrt_datasets/datasets/processed/coco/bench/"
    "construction_site_safety_bench.json"
)
DEFAULT_PERSON_GT = Path("../e-ovrt_datasets/datasets/processed/coco/bench/person_gt.json")


def _load_evaluate_bench() -> ModuleType:
    script_path = EVALUATE_BENCH_SCRIPT.resolve()
    if not script_path.is_file():
        raise FileNotFoundError(
            "Could not find e-ovrt_datasets evaluator at "
            f"{script_path}. Ensure the e-ovrt_datasets sibling repository is available, "
            "or pass explicit --bench-coco and --person-gt paths."
        )

    spec = importlib.util.spec_from_file_location("evaluate_bench", script_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not create module spec for BENCH evaluator: {script_path}")

    module = importlib.util.module_from_spec(spec)
    sys.modules["evaluate_bench"] = module
    spec.loader.exec_module(module)
    return module


def _resolve_bench_paths(
    bench_coco: Path | None,
    person_gt: Path | None,
) -> tuple[Path, Path]:
    if bench_coco is None or person_gt is None:
        _load_evaluate_bench()

    bench_coco_path = (bench_coco or DEFAULT_BENCH_COCO).resolve()
    person_gt_path = (person_gt or DEFAULT_PERSON_GT).resolve()
    if not bench_coco_path.is_file():
        raise FileNotFoundError(
            f"BENCH COCO file not found: {bench_coco_path}. Pass an explicit --bench-coco path."
        )
    if not person_gt_path.is_file():
        raise FileNotFoundError(
            f"BENCH person GT file not found: {person_gt_path}. Pass an explicit --person-gt path."
        )
    return bench_coco_path, person_gt_path


def run_evaluation(
    run_dir: Path,
    bench_coco: Path | None = None,
    person_gt: Path | None = None,
    iou_threshold: float = 0.5,
) -> EvalPerceptionResults:
    run_dir = Path(run_dir)
    detections_path = run_dir / "detections.jsonl"
    if not detections_path.is_file():
        raise FileNotFoundError(f"Detections file not found: {detections_path}")

    bench_coco_path, person_gt_path = _resolve_bench_paths(bench_coco, person_gt)
    evaluate_bench = _load_evaluate_bench()
    detections_by_img = evaluate_bench.load_detections([detections_path])
    images_by_filename, gt_by_image_id, cat_by_id = evaluate_bench.load_bench_coco(
        bench_coco_path
    )
    person_gt_records = evaluate_bench.load_person_gt(person_gt_path)

    per_class = []
    for class_name in cat_by_id.values():
        raw = evaluate_bench.evaluate_class(
            class_name,
            detections_by_img,
            images_by_filename,
            gt_by_image_id,
            cat_by_id,
            iou_threshold,
        )
        per_class.append(
            ClassResult(
                class_name=raw["class"],
                AP50=raw.get("AP50"),
                n_gt=raw.get("n_gt", 0),
                n_det=raw.get("n_det", 0),
            )
        )

    cr01_raw = evaluate_bench.evaluate_cr01(
        person_gt_records,
        detections_by_img,
        images_by_filename,
        iou_threshold,
    )
    result = EvalPerceptionResults(
        run_id=run_dir.name,
        benchmark=bench_coco_path.stem,
        iou_threshold=iou_threshold,
        per_class=per_class,
        cr01_detection_recall=cr01_raw.get("cr01_recall"),
        evaluated_at=datetime.now(timezone.utc).isoformat(),
    )
    (run_dir / "eval_perception.json").write_text(result.model_dump_json(indent=2))
    return result
