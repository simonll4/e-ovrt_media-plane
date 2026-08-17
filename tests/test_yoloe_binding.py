"""Tests del binding por construcción en el adaptador YOLOE (sin pesos)."""

from unittest.mock import MagicMock

import pytest

from eovrt_media.config.prompt_plan import PromptPhrase, PromptPlan
from eovrt_media.models.yoloe_adapter import YOLOEUltralyticsAdapter


FIXED_VOCABULARY = (
    ("person", "person"),
    ("helmet", "helmet"),
    ("vest", "vest"),
    ("bare_head", "bare head"),
)


def _plan():
    return PromptPlan(
        set_id="s",
        backend="yoloe",
        phrases=(
            PromptPhrase(0, "person", "person", "person"),
            PromptPhrase(1, "helmet", "helmet", "helmet", "positive_evidence", "CR-01"),
        ),
    )


def _fixed_plan(
    entries: tuple[tuple[str, str, str], ...] | None = None,
    *,
    backend: str = "yoloe",
) -> PromptPlan:
    values = entries or tuple((prompt_id, prompt_id, text) for prompt_id, text in FIXED_VOCABULARY)
    return PromptPlan(
        set_id="t1",
        backend=backend,
        phrases=tuple(
            PromptPhrase(index, text, prompt_id, canonical)
            for index, (prompt_id, canonical, text) in enumerate(values)
        ),
    )


def _fixed_adapter() -> YOLOEUltralyticsAdapter:
    adapter = YOLOEUltralyticsAdapter(fixed_vocabulary=FIXED_VOCABULARY)
    adapter.model = MagicMock()
    adapter.model.names = {index: text for index, (_id, text) in enumerate(FIXED_VOCABULARY)}
    return adapter


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


def test_fixed_vocabulary_accepts_exact_plan_without_set_classes():
    adapter = _fixed_adapter()

    adapter._ensure_classes(_fixed_plan())

    adapter.model.set_classes.assert_not_called()


@pytest.mark.parametrize(
    "plan",
    [
        _fixed_plan(
            (
                ("helmet", "helmet", "helmet"),
                ("person", "person", "person"),
                ("vest", "vest", "vest"),
                ("bare_head", "bare_head", "bare head"),
            )
        ),
        _fixed_plan(
            (
                ("person", "worker", "person"),
                ("helmet", "helmet", "helmet"),
                ("vest", "vest", "vest"),
                ("bare_head", "bare_head", "bare head"),
            )
        ),
        _fixed_plan(
            (
                ("person", "person", "person"),
                ("helmet", "helmet", "hard hat"),
                ("vest", "vest", "vest"),
                ("bare_head", "bare_head", "bare head"),
            )
        ),
        _fixed_plan(
            (
                ("person", "person", "person"),
                ("helmet", "helmet", "helmet"),
                ("vest", "vest", "vest"),
            )
        ),
        _fixed_plan(backend="default"),
    ],
    ids=("order", "canonical", "text", "missing", "backend"),
)
def test_fixed_vocabulary_rejects_incompatible_plans_without_set_classes(plan):
    adapter = _fixed_adapter()

    with pytest.raises(ValueError, match="PromptPlan incompatible"):
        adapter._ensure_classes(plan)

    adapter.model.set_classes.assert_not_called()


def test_fixed_vocabulary_validates_checkpoint_names_exactly():
    adapter = _fixed_adapter()
    adapter._validate_fixed_checkpoint_names()

    adapter.model.names = {0: "helmet", 1: "person", 2: "vest", 3: "bare head"}
    with pytest.raises(ValueError, match="Vocabulario del checkpoint YOLOE incompatible"):
        adapter._validate_fixed_checkpoint_names()


def test_dynamic_vocabulary_still_uses_set_classes():
    adapter = YOLOEUltralyticsAdapter()
    adapter.model = MagicMock()

    adapter._ensure_classes(_plan())

    adapter.model.set_classes.assert_called_once_with(["person", "helmet"])
