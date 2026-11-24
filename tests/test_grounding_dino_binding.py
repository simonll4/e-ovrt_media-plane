"""Tests del binding por construcción en el adaptador GDINO (sin pesos)."""

from eovrt_media.config.prompt_plan import PromptPhrase, PromptPlan
from eovrt_media.models.grounding_dino_adapter import GroundingDinoHFAdapter


def _plan():
    return PromptPlan(set_id="s", backend="gdino", phrases=(
        PromptPhrase(0, "hard hat", "helmet", "helmet", "positive_evidence", "CR-01"),
        PromptPhrase(1, "person", "person", "person"),
    ))


def test_backend_key():
    assert GroundingDinoHFAdapter.PROMPT_BACKEND == "gdino"


def test_span_resolves_to_canonical():
    ad = GroundingDinoHFAdapter()
    plan = _plan()
    out = ad._bind_span("hard hat", 0.9, [0, 0, 10, 10], plan.by_text(), plan.texts())
    assert out is not None
    assert out.label == "helmet"
    assert out.prompt_id == "helmet"
    assert out.source_prompt == "hard hat"
    assert out.condition_id == "CR-01"
    assert out.strategy == "positive_evidence"


def test_substring_span_resolves():
    ad = GroundingDinoHFAdapter()
    plan = _plan()
    # GDINO puede devolver un sub-span como "hat"
    out = ad._bind_span("hat", 0.8, [0, 0, 10, 10], plan.by_text(), plan.texts())
    assert out is not None
    assert out.prompt_id == "helmet"


def test_unresolved_span_returns_none():
    ad = GroundingDinoHFAdapter()
    plan = _plan()
    assert ad._bind_span("zzz unrelated", 0.9, [0, 0, 10, 10], plan.by_text(), plan.texts()) is None


def test_empty_span_is_discarded_not_bound_to_first_phrase():
    # "" in t es verdadero para toda frase: sin el corte, la caja iría a la
    # primera del plan ("hard hat" → helmet; en edir_v1, una infracción).
    ad = GroundingDinoHFAdapter()
    plan = _plan()
    assert ad._bind_span("", 0.9, [0, 0, 10, 10], plan.by_text(), plan.texts()) is None
