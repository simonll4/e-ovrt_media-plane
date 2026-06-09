"""Tests para los contratos de datos."""

import json

from eovrt_media.contracts import Detection, DetectionEvent, RunSummary, VisualUnit


class TestVisualUnit:
    def test_create_image_unit(self):
        unit = VisualUnit(
            unit_id="img_000001",
            source_path="data/samples/images/test.jpg",
            source_type="image",
            width=1280,
            height=720,
        )
        assert unit.unit_id == "img_000001"
        assert unit.frame_index is None
        assert unit.timestamp_ms is None
        assert unit.source_type == "image"

    def test_create_video_frame_unit(self):
        unit = VisualUnit(
            unit_id="frame_000042",
            source_path="data/samples/videos/test.mp4",
            source_type="video_frame",
            frame_index=42,
            width=1920,
            height=1080,
            timestamp_ms=1400.0,
        )
        assert unit.frame_index == 42
        assert unit.timestamp_ms == 1400.0

    def test_serialization(self):
        unit = VisualUnit(
            unit_id="img_000001",
            source_path="test.jpg",
            source_type="image",
            width=640,
            height=480,
        )
        data = json.loads(unit.model_dump_json())
        assert data["unit_id"] == "img_000001"
        assert data["width"] == 640


class TestDetection:
    def test_create_detection(self):
        det = Detection(
            label="person",
            prompt_id="person",
            confidence=0.84,
            bbox_xyxy=[120.0, 80.0, 400.0, 700.0],
            bbox_norm_xyxy=[0.093, 0.111, 0.312, 0.972],
            model_name="grounding_dino_hf",
        )
        assert det.label == "person"
        assert det.confidence == 0.84
        assert len(det.bbox_xyxy) == 4
        assert len(det.bbox_norm_xyxy) == 4

    def test_detection_without_prompt_id(self):
        det = Detection(
            label="unknown_object",
            confidence=0.5,
            bbox_xyxy=[10, 10, 100, 100],
            bbox_norm_xyxy=[0.01, 0.01, 0.1, 0.1],
            model_name="mock",
        )
        assert det.prompt_id is None


class TestDetectionEvent:
    def test_create_event(self):
        event = DetectionEvent(
            run_id="20260609_001",
            unit_id="img_000001",
            source_path="test.jpg",
            model_adapter="grounding_dino_hf",
            prompt_version="cr01_cr02_v1",
            detections=[
                Detection(
                    label="person",
                    prompt_id="person",
                    confidence=0.84,
                    bbox_xyxy=[120, 80, 400, 700],
                    bbox_norm_xyxy=[0.09, 0.11, 0.31, 0.97],
                    model_name="grounding_dino_hf",
                )
            ],
            timing_ms={"total": 112.4, "inference": 101.7},
        )
        assert len(event.detections) == 1
        assert event.timing_ms["inference"] == 101.7

    def test_jsonl_serialization(self):
        event = DetectionEvent(
            run_id="test_run",
            unit_id="img_000001",
            source_path="test.jpg",
            model_adapter="mock",
            prompt_version="v1",
            detections=[],
            timing_ms={"total": 10.0, "inference": 5.0},
        )
        line = event.model_dump_json()
        parsed = json.loads(line)
        assert parsed["run_id"] == "test_run"
        assert isinstance(parsed["detections"], list)


class TestRunSummary:
    def test_create_summary(self):
        summary = RunSummary(
            run_id="20260609_001",
            scenario="DBE",
            model_adapter="grounding_dino_hf",
            prompt_version="cr01_cr02_v1",
            source_count=12,
            units_processed=12,
            units_failed=0,
            total_detections=45,
            avg_latency_ms=118.3,
            p50_latency_ms=115.0,
            p95_latency_ms=145.0,
            started_at="2026-06-09T10:00:00Z",
            finished_at="2026-06-09T10:00:08Z",
        )
        assert summary.units_processed == 12
        assert summary.avg_latency_ms == 118.3
