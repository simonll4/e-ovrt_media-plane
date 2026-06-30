"""Tests del binding por construcción en el adaptador YOLOE (sin pesos)."""

from eovrt_media.config.prompt_plan import PromptPhrase, PromptPlan
from eovrt_media.models.yoloe_adapter import YOLOEUltralyticsAdapter


def _plan():
    return PromptPlan(set_id="s", backend="yoloe", phrases=(
        PromptPhrase(0, "person", "person", "person"),
        PromptPhrase(1, "helmet", "helmet", "helmet", "positive_evidence", "CR-01"),
    ))


def test_backend_key():
    assert YOLOEUltralyticsAdapter.PROMPT_BACKEND == "yoloe"


def test_class_id_maps_to_canonical_exact():
    ad = YOLOEUltralyticsAdapter()
    # cls_id=1 → índice 1 del plan → helmet
    out = ad._decode_boxes([[0, 0, 10, 10]], [0.9], [1.0], _plan())
    assert len(out) == 1
    assert out[0].label == "helmet"
    assert out[0].prompt_id == "helmet"
    assert out[0].source_prompt == "helmet"
    assert out[0].condition_id == "CR-01"
    assert out[0].strategy == "positive_evidence"


def test_class_id_zero_maps_to_first_phrase():
    ad = YOLOEUltralyticsAdapter()
    out = ad._decode_boxes([[0, 0, 10, 10]], [0.7], [0.0], _plan())
    assert out[0].prompt_id == "person"
    assert out[0].condition_id is None


def test_out_of_range_class_id_is_dropped():
    ad = YOLOEUltralyticsAdapter()
    # cls_id=9 está fuera del rango del plan (2 frases) → se descarta, no crashea
    out = ad._decode_boxes(
        [[0, 0, 10, 10], [0, 0, 20, 20]], [0.9, 0.8], [9.0, 1.0], _plan()
    )
    assert len(out) == 1
    assert out[0].prompt_id == "helmet"
