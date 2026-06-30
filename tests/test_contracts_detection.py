"""Tests for detection contracts."""

from eovrt_media.contracts.detection import RawDetection, Detection


def test_raw_detection_carries_prompt_metadata():
    raw = RawDetection(
        label="helmet", score=0.9, box_xyxy=[0, 0, 10, 10],
        prompt_id="helmet", source_prompt="hard hat",
        strategy="positive_evidence", condition_id="CR-01",
    )
    assert raw.strategy == "positive_evidence"
    assert raw.condition_id == "CR-01"


def test_detection_metadata_defaults_none():
    det = Detection(label="helmet", confidence=0.9, bbox_xyxy=[0, 0, 10, 10], bbox_norm_xyxy=[0, 0, 1, 1])
    assert det.strategy is None
    assert det.condition_id is None
