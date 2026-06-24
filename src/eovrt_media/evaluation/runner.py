from __future__ import annotations

import hashlib
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
_EVALUATE_BENCH_MODULE_PREFIX = "eovrt_media._evaluate_bench_sibling"
_EVALUATE_BENCH_CACHE: dict[Path, ModuleType] = {}


def _resolve_evaluate_bench_script() -> Path:
    script_path = EVALUATE_BENCH_SCRIPT.resolve()
    if not script_path.is_file():
        raise FileNotFoundError(
            "Required e-ovrt_datasets sibling evaluator script not found at "
            f"{script_path}. Ensure the evaluator script is present at this expected path."
        )
    return script_path


def _evaluate_bench_module_name(script_path: Path) -> str:
    digest = hashlib.sha256(str(script_path).encode()).hexdigest()
    return f"{_EVALUATE_BENCH_MODULE_PREFIX}_{digest}"


def _load_evaluate_bench() -> ModuleType:
    script_path = _resolve_evaluate_bench_script()
    cached_module = _EVALUATE_BENCH_CACHE.get(script_path)
    if cached_module is not None:
        return cached_module

    module_name = _evaluate_bench_module_name(script_path)
    spec = importlib.util.spec_from_file_location(module_name, script_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not create module spec for BENCH evaluator: {script_path}")

    module = importlib.util.module_from_spec(spec)
    previous_module = sys.modules.get(module_name)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        if previous_module is None:
            sys.modules.pop(module_name, None)
        else:
            sys.modules[module_name] = previous_module
        raise
    _EVALUATE_BENCH_CACHE[script_path] = module
    return module


def _resolve_bench_paths(
    bench_coco: Path | None,
    person_gt: Path | None,
) -> tuple[Path, Path]:
    if bench_coco is None or person_gt is None:
        _resolve_evaluate_bench_script()

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
