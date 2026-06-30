"""Tests del NMS per-clase (per canónico) del adaptador Grounding DINO."""

from __future__ import annotations

from eovrt_media.contracts.detection import RawDetection
from eovrt_media.models.grounding_dino_adapter import _nms_per_canonical


def _det(label: str, score: float, box: list[float]) -> RawDetection:
    return RawDetection(label=label, score=score, box_xyxy=box)


def test_collapses_overlapping_same_canonical():
    """Dos cajas muy solapadas del mismo canónico → sobrevive la de mayor score."""
    dets = [
        _det("person", 0.9, [0, 0, 100, 100]),
        _det("person", 0.7, [5, 5, 102, 102]),  # IoU alto con la anterior
    ]
    kept = _nms_per_canonical(dets, iou_threshold=0.5)
    assert len(kept) == 1
    assert kept[0].score == 0.9


def test_keeps_overlapping_different_canonical():
    """Cajas solapadas de clases distintas se conservan (NMS per-clase, no agnostic)."""
    dets = [
        _det("person", 0.9, [0, 0, 100, 100]),
        _det("helmet", 0.8, [10, 10, 40, 40]),  # casco dentro de la persona
    ]
    kept = _nms_per_canonical(dets, iou_threshold=0.5)
    assert len(kept) == 2
    assert {d.label for d in kept} == {"person", "helmet"}


def test_keeps_disjoint_same_canonical():
    """Cajas del mismo canónico sin solape se conservan ambas."""
    dets = [
        _det("person", 0.9, [0, 0, 50, 50]),
        _det("person", 0.8, [200, 200, 260, 260]),
    ]
    kept = _nms_per_canonical(dets, iou_threshold=0.5)
    assert len(kept) == 2


def test_empty_input_returns_empty():
    assert _nms_per_canonical([], iou_threshold=0.5) == []


def test_collapses_duplicate_phrasings_of_same_canonical():
    """Distintas frases (source_prompt) del mismo canónico también se deduplican."""
    dets = [
        RawDetection(label="person", score=0.9, box_xyxy=[0, 0, 100, 100],
                     source_prompt="person"),
        RawDetection(label="person", score=0.6, box_xyxy=[4, 4, 104, 104],
                     source_prompt="worker"),
    ]
    kept = _nms_per_canonical(dets, iou_threshold=0.5)
    assert len(kept) == 1
    assert kept[0].source_prompt == "person"
