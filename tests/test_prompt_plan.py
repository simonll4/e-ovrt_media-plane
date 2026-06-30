import pytest

from eovrt_media.config.prompt_plan import PromptPhrase, PromptPlan


def _plan():
    return PromptPlan(
        set_id="ppe_v2", backend="gdino",
        phrases=(
            PromptPhrase(0, "hard hat", "helmet", "helmet", "positive_evidence", "CR-01"),
            PromptPhrase(1, "safety helmet", "helmet", "helmet", "positive_evidence", "CR-01"),
            PromptPhrase(2, "person", "person", "person"),
        ),
    )


def test_texts_in_order():
    assert _plan().texts() == ["hard hat", "safety helmet", "person"]


def test_by_index_resolves_class_id():
    plan = _plan()
    assert plan.by_index()[1].canonical == "helmet"
    assert plan.by_index()[2].prompt_id == "person"


def test_by_text_exact_lookup():
    plan = _plan()
    assert plan.by_text()["safety helmet"].prompt_id == "helmet"


def test_synonyms_collapse_to_same_canonical():
    plan = _plan()
    assert plan.by_index()[0].canonical == plan.by_index()[1].canonical == "helmet"


def test_from_texts_helper():
    plan = PromptPlan.from_texts(["object"], backend="gdino")
    assert plan.texts() == ["object"]
    assert plan.by_index()[0].prompt_id == "object"
    assert plan.by_index()[0].canonical == "object"
    assert plan.backend == "gdino"


def test_out_of_order_phrases_rejected():
    with pytest.raises(ValueError):
        PromptPlan(set_id="x", backend="y", phrases=(
            PromptPhrase(2, "c", "c", "c"),
            PromptPhrase(0, "a", "a", "a"),
        ))
