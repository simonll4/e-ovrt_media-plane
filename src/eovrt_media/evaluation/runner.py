from pathlib import Path

from .schemas import EvalPerceptionResults


def run_evaluation(
    run_dir: Path,
    bench_coco: Path | None = None,
    person_gt: Path | None = None,
    iou_threshold: float = 0.5,
) -> EvalPerceptionResults:
    raise NotImplementedError
