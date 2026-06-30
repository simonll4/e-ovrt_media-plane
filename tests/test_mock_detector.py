"""Tests del MockDetector: binding por construcción desde el PromptPlan."""

from PIL import Image

from eovrt_media.config.prompt_plan import PromptPhrase, PromptPlan
from eovrt_media.models.mock_detector import MockDetectorAdapter


def _plan():
    return PromptPlan(set_id="s", backend="default", phrases=(
        PromptPhrase(0, "person", "person", "person"),
        PromptPhrase(1, "helmet", "helmet", "helmet", "positive_evidence", "CR-01"),
    ))


def test_mock_binds_each_detection_to_its_phrase():
    out = MockDetectorAdapter(seed=7).predict(Image.new("RGB", (128, 128)), _plan())
    assert out, "el mock debería producir al menos una detección con este seed"
    expected = {
        "person": ("person", None, None),
        "helmet": ("helmet", "positive_evidence", "CR-01"),
    }
    for d in out:
        canonical, strategy, condition = expected[d.prompt_id]
        assert d.label == canonical          # label = canonical
        assert d.source_prompt == d.prompt_id
        assert d.strategy == strategy
        assert d.condition_id == condition


def test_mock_default_backend():
    assert MockDetectorAdapter.PROMPT_BACKEND == "default"
