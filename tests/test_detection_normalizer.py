"""Tests del DetectionNormalizer: confía en el binding del adaptador."""

from eovrt_media.contracts.detection import RawDetection
from eovrt_media.postprocessing.detection_normalizer import DetectionNormalizer


def test_normalizer_trusts_adapter_binding():
    raw = [
        RawDetection(
            label="helmet", prompt_id="helmet", source_prompt="hard hat",
            strategy="positive_evidence", condition_id="CR-01",
            score=0.9, box_xyxy=[0, 0, 50, 50],
        )
    ]
    out = DetectionNormalizer(min_confidence=0.1).normalize(raw, 100, 100, "mock")
    assert len(out) == 1
    assert out[0].label == "helmet"
    assert out[0].prompt_id == "helmet"
    assert out[0].source_prompt == "hard hat"
    assert out[0].strategy == "positive_evidence"
    assert out[0].condition_id == "CR-01"


def test_normalizer_confidence_filter():
    raw = [RawDetection(label="x", prompt_id="x", score=0.05, box_xyxy=[0, 0, 50, 50])]
    assert DetectionNormalizer(min_confidence=0.25).normalize(raw, 100, 100, "mock") == []
