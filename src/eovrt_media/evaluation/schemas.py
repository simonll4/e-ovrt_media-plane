from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class ClassResult(BaseModel):
    class_name: str
    AP50: float | None
    n_gt: int
    n_det: int


class EvalPerceptionResults(BaseModel):
    type: Literal["perception"] = "perception"
    run_id: str
    benchmark: str
    iou_threshold: float
    per_class: list[ClassResult]
    cr01_detection_recall: float | None
    evaluated_at: str
