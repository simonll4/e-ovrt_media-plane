"""Tests para JSONLSink y SummarySink."""

import json

import pytest

import eovrt_media.sinks.jsonl_sink as jsonl_sink_mod
from eovrt_media.sinks import JSONLSink
from eovrt_media.sinks.jsonl_sink import atomic_write_json
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
    assert "read_ms" not in ev_loaded["timing"]
    assert len(ev_loaded["detections"]) == 1

    met_loaded = json.loads(lines[1])
    assert met_loaded["run_id"] == "run_123"
    assert met_loaded["latency_total_ms"] == 10.5
    assert met_loaded["detections_count"] == 1
    assert "total_ms" not in met_loaded
    assert "inference_ms" not in met_loaded
    assert "detection_count" not in met_loaded

    err_loaded = json.loads(lines[2])
    assert err_loaded["run_id"] == "run_123"
    assert err_loaded["message"] == "Test error"


def test_atomic_write_json_no_trunca_archivo_existente_ante_fallo(tmp_path, monkeypatch):
    """Ancla Fix 1: si el proceso muere a mitad de la escritura (disco lleno,
    kill, OOM), el archivo real (summary.json/run_manifest.json/...) no debe
    quedar truncado ni corrupto — la escritura pasa por un .tmp que sólo se
    promueve con os.replace() si se completó por entero."""
    output = tmp_path / "summary.json"
    output.write_text(json.dumps({"status": "previo_ok"}))

    def boom(*_args, **_kwargs):
        raise OSError("fallo simulado a mitad de escritura")

    monkeypatch.setattr(jsonl_sink_mod.json, "dump", boom)

    with pytest.raises(OSError):
        atomic_write_json(output, {"status": "nuevo"})

    # El destino real nunca se tocó: sigue con el contenido previo, íntegro
    # (el fallo ocurrió escribiendo el .tmp, antes del os.replace() final).
    assert json.loads(output.read_text()) == {"status": "previo_ok"}
    # Tampoco debe quedar el .tmp huérfano (Fix B).
    assert list(output.parent.glob("*.tmp")) == []


def test_atomic_write_json_limpia_tmp_ante_fallo(tmp_path, monkeypatch):
    """Ancla Fix B: si json.dump falla a mitad de escritura del .tmp, no debe
    quedar un archivo *.tmp huérfano en el directorio destino."""
    output = tmp_path / "summary.json"

    def boom(*_args, **_kwargs):
        raise ValueError("fallo simulado a mitad de escritura")

    monkeypatch.setattr(jsonl_sink_mod.json, "dump", boom)

    with pytest.raises(ValueError):
        atomic_write_json(output, {"status": "nuevo"})

    assert list(tmp_path.glob("*.tmp")) == []
    assert not output.exists()
