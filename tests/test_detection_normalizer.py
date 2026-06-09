"""Tests para el normalizador de detecciones (DetectionNormalizer)."""

from eovrt_media.postprocessing import DetectionNormalizer
from eovrt_media.contracts import RawDetection
from eovrt_media.config import PromptItem


def test_normalizer_filtering():
    normalizer = DetectionNormalizer(
        min_confidence=0.5,
        min_box_area_px=100.0,
        normalize_boxes=True,
    )

    raw_detections = [
        # Pass (confidence 0.8, area 200)
        RawDetection(label="person", score=0.8, box_xyxy=[10.0, 10.0, 30.0, 20.0]),
        # Filtered by confidence (0.4 < 0.5)
        RawDetection(label="helmet", score=0.4, box_xyxy=[10.0, 10.0, 30.0, 20.0]),
        # Filtered by area (80 < 100)
        RawDetection(label="vest", score=0.9, box_xyxy=[10.0, 10.0, 20.0, 18.0]),
    ]

    prompt_items = [
        PromptItem(id="person", text="person"),
        PromptItem(id="helmet", text="safety helmet"),
    ]

    detections = normalizer.normalize(
        raw_detections=raw_detections,
        width=100,
        height=100,
        model_name="mock",
        prompt_items=prompt_items,
    )

    assert len(detections) == 1
    assert detections[0].label == "person"
    assert detections[0].prompt_id == "person"
    assert detections[0].confidence == 0.8
    assert detections[0].bbox_norm_xyxy == [0.1, 0.1, 0.3, 0.2]
    assert detections[0].area_px == 200.0
