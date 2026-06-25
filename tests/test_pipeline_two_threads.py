from __future__ import annotations

import json
import threading
from pathlib import Path

import cv2
import numpy as np

from eovrt_media.config import load_run_config
from eovrt_media.contracts import VisualUnit
from eovrt_media.contracts.detection import RawDetection
from eovrt_media.models.mock_detector import MockDetectorAdapter
from eovrt_media.runtime import run_pipeline
from eovrt_media.sources.base import BaseSource


CONFIGS_DIR = Path(__file__).parent.parent / "configs"


def _create_test_images(folder: Path, count: int = 5) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    for index in range(count):
        image = np.zeros((480, 640, 3), dtype=np.uint8)
        image[:] = (50 + index * 30, 100, 200)
        cv2.imwrite(str(folder / f"test_{index:03d}.jpg"), image)


def _mock_config(tmp_path: Path):
    images_dir = tmp_path / "images"
    _create_test_images(images_dir)
    config = load_run_config(CONFIGS_DIR / "runs" / "mock.yaml")
    config.source.path = str(images_dir)
    config.outputs.base_dir = str(tmp_path / "runs")
    config.outputs.run_dir = str(tmp_path / "runs")
    config.outputs.save_previews = False
    return config


class TestProducerConsumerPipeline:
    def test_pipeline_writes_preview_from_payload_when_no_detections(
        self, tmp_path: Path, monkeypatch
    ):
        class PayloadOnlySource(BaseSource):
            def __iter__(self):
                yield VisualUnit(
                    unit_id="unit-empty",
                    source_id="camera-1",
                    source_type="video_frame",
                    frame_index=1,
                    timestamp_ms=0.0,
                    width=8,
                    height=8,
                    pixel_data=np.zeros((8, 8, 3), dtype=np.uint8),
                )

            def __len__(self):
                return 1

        import eovrt_media.runtime.pipeline as pipeline_module

        monkeypatch.setattr(pipeline_module, "create_source", lambda _config: PayloadOnlySource())
        monkeypatch.setattr(MockDetectorAdapter, "forward", lambda *_args: [])
        config = _mock_config(tmp_path)
        config.outputs.save_previews = True
        config.outputs.preview_max = 1

        run_id = run_pipeline(config)

        preview_path = Path(config.outputs.base_dir) / run_id / "previews" / "unit-empty.preview.jpg"
        assert preview_path.exists()

    def test_pipeline_writes_preview_from_payload_without_source_path(
        self, tmp_path: Path, monkeypatch
    ):
        class PayloadOnlySource(BaseSource):
            def __iter__(self):
                yield VisualUnit(
                    unit_id="unit-1",
                    source_id="camera-1",
                    source_type="video_frame",
                    frame_index=1,
                    timestamp_ms=0.0,
                    width=8,
                    height=8,
                    pixel_data=np.zeros((8, 8, 3), dtype=np.uint8),
                )

            def __len__(self):
                return 1

        def fixed_forward(self, unit, prompts):
            return [
                RawDetection(
                    label="person", score=0.9, box_xyxy=[1.0, 1.0, 6.0, 6.0]
                )
            ]

        import eovrt_media.runtime.pipeline as pipeline_module

        monkeypatch.setattr(pipeline_module, "create_source", lambda _config: PayloadOnlySource())
        monkeypatch.setattr(MockDetectorAdapter, "forward", fixed_forward)
        config = _mock_config(tmp_path)
        config.outputs.save_previews = True
        config.outputs.preview_max = 1

        run_id = run_pipeline(config)

        preview_path = Path(config.outputs.base_dir) / run_id / "previews" / "unit-1.preview.jpg"
        assert preview_path.exists()
        assert cv2.imread(str(preview_path)) is not None

    def test_preview_write_error_is_recorded_without_failing_unit(self, tmp_path: Path, monkeypatch):
        import eovrt_media.runtime.pipeline as pipeline_module

        def fixed_forward(self, unit, prompts):
            return [
                RawDetection(
                    label="person", score=0.9, box_xyxy=[1.0, 1.0, 6.0, 6.0]
                )
            ]

        def fail_preview(*_args, **_kwargs):
            raise OSError("disk full")

        monkeypatch.setattr(MockDetectorAdapter, "forward", fixed_forward)
        monkeypatch.setattr(pipeline_module, "draw_detections_rgb", fail_preview)
        config = _mock_config(tmp_path)
        config.outputs.save_previews = True
        config.outputs.preview_max = 1

        run_id = run_pipeline(config)
        run_dir = Path(config.outputs.base_dir) / run_id
        summary = json.loads((run_dir / "summary.json").read_text())
        errors = [json.loads(line) for line in (run_dir / "errors.jsonl").read_text().splitlines()]

        assert summary["units_processed"] == 5
        assert summary["units_failed"] == 0
        assert any(error["stage"] == "preview" and error["recoverable"] for error in errors)

    def test_preview_max_counts_attempts_even_when_write_fails(
        self, tmp_path: Path, monkeypatch
    ):
        import eovrt_media.runtime.pipeline as pipeline_module

        previewed_units = []
        draw_preview = pipeline_module.draw_detections_rgb

        def fixed_forward(self, unit, prompts):
            return [
                RawDetection(
                    label="person", score=0.9, box_xyxy=[1.0, 1.0, 6.0, 6.0]
                )
            ]

        def capture_preview(payload, detections, output_path):
            previewed_units.append(output_path.name)
            draw_preview(payload, detections, output_path)

        def fail_detection_write(self, event):
            raise OSError("detections sink unavailable")

        monkeypatch.setattr(MockDetectorAdapter, "forward", fixed_forward)
        monkeypatch.setattr(pipeline_module, "draw_detections_rgb", capture_preview)
        monkeypatch.setattr(
            pipeline_module.RunArtifactWriter,
            "write_detection",
            fail_detection_write,
        )
        config = _mock_config(tmp_path)
        config.outputs.save_previews = True
        config.outputs.preview_max = 1

        run_id = run_pipeline(config)
        run_dir = Path(config.outputs.base_dir) / run_id
        summary = json.loads((run_dir / "summary.json").read_text())

        assert previewed_units == ["img_000000.preview.jpg"]
        assert summary["units_processed"] == 0
        assert summary["units_failed"] == 5

    def test_preview_uses_raw_model_coordinates_before_reprojection(
        self, tmp_path: Path, monkeypatch
    ):
        class NonIdentitySource(BaseSource):
            def __iter__(self):
                yield VisualUnit(
                    unit_id="unit-transformed",
                    source_id="camera-1",
                    source_type="video_frame",
                    frame_index=1,
                    timestamp_ms=0.0,
                    width=200,
                    height=100,
                    pixel_data=np.zeros((100, 200, 3), dtype=np.uint8),
                )

            def __len__(self):
                return 1

        import eovrt_media.runtime.pipeline as pipeline_module

        raw_box = [200.0, 320.0, 400.0, 440.0]
        captured_boxes = []
        draw_preview = pipeline_module.draw_detections_rgb

        def capture_preview(payload, detections, output_path):
            captured_boxes.extend(detection.box_xyxy for detection in detections)
            draw_preview(payload, detections, output_path)

        def fixed_forward(self, unit, prompts):
            return [RawDetection(label="person", score=0.9, box_xyxy=raw_box)]

        monkeypatch.setattr(pipeline_module, "create_source", lambda _config: NonIdentitySource())
        monkeypatch.setattr(pipeline_module, "draw_detections_rgb", capture_preview)
        monkeypatch.setattr(MockDetectorAdapter, "forward", fixed_forward)
        config = _mock_config(tmp_path)
        config.outputs.save_previews = True
        config.outputs.preview_max = 1

        run_id = run_pipeline(config)
        event = json.loads(
            (Path(config.outputs.base_dir) / run_id / "detections.jsonl").read_text()
        )

        assert captured_boxes == [raw_box]
        assert event["detections"][0]["bbox_xyxy"] != raw_box
        assert (Path(config.outputs.base_dir) / run_id / "previews" / "unit-transformed.preview.jpg").exists()

    def test_pipeline_calls_forward_with_normalized_units(self, tmp_path: Path, monkeypatch):
        observed_units = []
        observed_threads = []

        def forward(self, unit, prompts):
            observed_units.append(unit)
            observed_threads.append(threading.current_thread().name)
            return self.predict_image_from_normalized(unit, prompts)

        def predict_image_from_normalized(self, unit, prompts):
            from PIL import Image

            return self.predict(Image.fromarray(unit.payload), prompts)

        monkeypatch.setattr(MockDetectorAdapter, "forward", forward, raising=False)
        monkeypatch.setattr(
            MockDetectorAdapter,
            "predict_image_from_normalized",
            predict_image_from_normalized,
            raising=False,
        )

        run_pipeline(_mock_config(tmp_path))

        assert len(observed_units) == 5
        assert all(unit.target_size == (640, 640) for unit in observed_units)
        assert observed_threads == ["MainThread"] * 5

    def test_deterministic_two_runs_have_identical_detections(self, tmp_path: Path):
        config = _mock_config(tmp_path)
        run_id_1 = run_pipeline(config)
        detections_1 = (Path(config.outputs.base_dir) / run_id_1 / "detections.jsonl").read_text()

        config.outputs.base_dir = str(tmp_path / "runs-2")
        config.outputs.run_dir = str(tmp_path / "runs-2")
        run_id_2 = run_pipeline(config)
        detections_2 = (Path(config.outputs.base_dir) / run_id_2 / "detections.jsonl").read_text()

        events_1 = [json.loads(line)["detections"] for line in detections_1.splitlines()]
        events_2 = [json.loads(line)["detections"] for line in detections_2.splitlines()]
        assert events_1 == events_2

    def test_clean_shutdown_processes_all_units(self, tmp_path: Path):
        config = _mock_config(tmp_path)
        run_id = run_pipeline(config)
        summary = json.loads(
            (Path(config.outputs.base_dir) / run_id / "summary.json").read_text()
        )
        assert summary["units_processed"] == 5
        assert summary["units_failed"] == 0

    def test_rate_gate_applies_stride(self, tmp_path: Path):
        config = _mock_config(tmp_path)
        config.rate_control.stride = 2
        run_id = run_pipeline(config)
        summary = json.loads(
            (Path(config.outputs.base_dir) / run_id / "summary.json").read_text()
        )
        assert summary["units_processed"] == 3

    def test_bounded_freshness_policy_completes(self, tmp_path: Path):
        config = _mock_config(tmp_path)
        config.rate_control.policy = "bounded_freshness"
        config.rate_control.buffer_size = 2
        run_id = run_pipeline(config)
        summary = json.loads(
            (Path(config.outputs.base_dir) / run_id / "summary.json").read_text()
        )
        assert summary["run_descriptor"]["rate_control"]["policy"] == "bounded_freshness"
        total = summary["units_processed"] + summary["units_failed"] + summary["units_dropped"]
        assert total <= 5

    def test_producer_normalize_error_is_isolated(self, tmp_path: Path, monkeypatch):
        import eovrt_media.runtime.pipeline as pipeline_module

        call_count = [0]
        real_normalize = pipeline_module.normalize_spatial

        def flaky_normalize(unit, spec, payload_format):
            call_count[0] += 1
            if call_count[0] == 2:
                raise ValueError("simulated normalize error")
            return real_normalize(unit, spec, payload_format)

        monkeypatch.setattr(pipeline_module, "normalize_spatial", flaky_normalize)

        config = _mock_config(tmp_path)
        run_id = run_pipeline(config)
        summary = json.loads(
            (Path(config.outputs.base_dir) / run_id / "summary.json").read_text()
        )

        assert summary["units_failed"] >= 1
        assert summary["units_processed"] >= 3

        errors_path = Path(config.outputs.base_dir) / run_id / "errors.jsonl"
        errors = [json.loads(line) for line in errors_path.read_text().splitlines()]
        assert any(e["stage"] == "normalize" for e in errors)

    def test_inference_error_is_isolated(self, tmp_path: Path, monkeypatch):
        call_count = [0]
        original_forward = MockDetectorAdapter.forward

        def flaky_forward(self, unit, prompts):
            call_count[0] += 1
            if call_count[0] == 1:
                raise RuntimeError("simulated inference error")
            return original_forward(self, unit, prompts)

        monkeypatch.setattr(MockDetectorAdapter, "forward", flaky_forward)

        config = _mock_config(tmp_path)
        run_id = run_pipeline(config)
        summary = json.loads(
            (Path(config.outputs.base_dir) / run_id / "summary.json").read_text()
        )

        assert summary["units_failed"] >= 1
        assert summary["units_processed"] >= 3

        errors_path = Path(config.outputs.base_dir) / run_id / "errors.jsonl"
        errors = [json.loads(line) for line in errors_path.read_text().splitlines()]
        assert any(e["stage"] == "inference" for e in errors)
