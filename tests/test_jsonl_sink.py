"""Tests para JSONLSink y SummarySink."""

import json
from eovrt_media.sinks import JSONLSink
from eovrt_media.contracts import DetectionEvent, MetricSample, ErrorEvent, Detection


def test_jsonl_sink_flow(tmp_path):
    output_file = tmp_path / "detections.jsonl"
    sink = JSONLSink(output_file)
    sink.open()

    event = DetectionEvent(
        run_id="run_123",
        unit_id="unit_001",
        source={
            "source_id": "test.jpg",
            "source_type": "image",
            "width": 640,
            "height": 480,
        },
        model={
            "name": "mock",
            "device": "cpu",
        },
        prompts={
            "prompt_set_id": "v1",
        },
        detections=[
            Detection(
                label="person",
                prompt_id="person",
                confidence=0.9,
                bbox_xyxy=[10, 10, 50, 50],
                bbox_norm_xyxy=[0.01, 0.01, 0.08, 0.08],
                area_px=1600.0,
            )
        ],
        timing={},
    )

    sink.write_event(event)

    metric = MetricSample(
        run_id="run_123",
        unit_id="unit_001",
        latency_total_ms=10.5,
        latency_inference_ms=8.0,
        detections_count=1,
    )
    
    sink.write_metric(metric)

    error = ErrorEvent(
        run_id="run_123",
        unit_id="unit_001",
        stage="inference",
        message="Test error",
    )
    sink.write_error(error)

    sink.close()

    assert output_file.exists()

    with open(output_file, encoding="utf-8") as f:
        lines = f.readlines()

    assert len(lines) == 3
    
    ev_loaded = json.loads(lines[0])
    assert ev_loaded["run_id"] == "run_123"
    assert ev_loaded["unit_id"] == "unit_001"
    assert ev_loaded["source"]["source_id"] == "test.jpg"
    assert len(ev_loaded["detections"]) == 1

    met_loaded = json.loads(lines[1])
    assert met_loaded["run_id"] == "run_123"
    assert met_loaded["latency_total_ms"] == 10.5
    assert met_loaded["detections_count"] == 1

    err_loaded = json.loads(lines[2])
    assert err_loaded["run_id"] == "run_123"
    assert err_loaded["message"] == "Test error"
