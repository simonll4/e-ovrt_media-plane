"""Tests para normalize_spatial, prepare_model_input y DetectionNormalizer con transform."""

from __future__ import annotations

import numpy as np
import pytest
import cv2
from pathlib import Path

from eovrt_media.contracts import VisualUnit
from eovrt_media.contracts.normalized_unit import (
    NormalizedUnit, PayloadFormat, ResizeTransform
)
from eovrt_media.models.base import ModelInputSpec
from eovrt_media.preprocessing.normalizer import normalize_spatial, prepare_model_input


def _make_visual_unit(tmp_path: Path, width: int = 800, height: int = 600) -> VisualUnit:
    img = np.zeros((height, width, 3), dtype=np.uint8)
    img[:] = (100, 150, 200)
    p = tmp_path / "test.jpg"
    cv2.imwrite(str(p), cv2.cvtColor(img, cv2.COLOR_RGB2BGR))
    return VisualUnit(
        unit_id="u1",
        source_type="image",
        width=width,
        height=height,
        path=str(p),
    )


class TestNormalizeSpatial:
    def test_output_shape_letterbox(self, tmp_path):
        unit = _make_visual_unit(tmp_path, width=800, height=600)
        spec = ModelInputSpec(target_size=(640, 640), resize_mode="letterbox")
        result = normalize_spatial(unit, spec, PayloadFormat.UINT8_RGB)
        assert isinstance(result, NormalizedUnit)
        assert result.payload.shape == (640, 640, 3)
        assert result.payload.dtype == np.uint8
        assert result.target_size == (640, 640)

    def test_transform_scale_computation(self, tmp_path):
        unit = _make_visual_unit(tmp_path, width=800, height=400)
        spec = ModelInputSpec(target_size=(640, 640), resize_mode="letterbox")
        result = normalize_spatial(unit, spec, PayloadFormat.UINT8_RGB)
        # scale = min(640/800, 640/400) = min(0.8, 1.6) = 0.8
        # scaled: 800*0.8=640, 400*0.8=320 → pad_y = (640-320)/2 = 160
        assert result.transform.scale_x == pytest.approx(0.8, abs=0.01)
        assert result.transform.scale_y == pytest.approx(0.8, abs=0.01)
        assert result.transform.pad_y == pytest.approx(160.0, abs=1.0)
        assert result.transform.pad_x == pytest.approx(0.0, abs=1.0)

    def test_metadata_propagated(self, tmp_path):
        unit = _make_visual_unit(tmp_path, width=800, height=600)
        spec = ModelInputSpec(target_size=(640, 640), resize_mode="letterbox")
        result = normalize_spatial(unit, spec, PayloadFormat.UINT8_RGB)
        assert result.orig_width == 800
        assert result.orig_height == 600
        assert result.unit_id == "u1"

    def test_fp16_payload_format(self, tmp_path):
        unit = _make_visual_unit(tmp_path)
        spec = ModelInputSpec(target_size=(640, 640))
        result = normalize_spatial(unit, spec, PayloadFormat.FP16)
        assert result.payload.dtype == np.float16
        assert result.payload.min() >= 0.0
        assert result.payload.max() <= 1.0
        assert result.payload_format == PayloadFormat.FP16

    def test_fp32_payload_format(self, tmp_path):
        unit = _make_visual_unit(tmp_path)
        spec = ModelInputSpec(target_size=(640, 640))
        result = normalize_spatial(unit, spec, PayloadFormat.FP32)
        assert result.payload.dtype == np.float32
        assert result.payload.min() >= 0.0
        assert result.payload.max() <= 1.0
        assert result.payload_format == PayloadFormat.FP32

    def test_run_id_propagated(self, tmp_path):
        unit = _make_visual_unit(tmp_path)
        unit = unit.model_copy(update={"run_id": "test_run_123"})
        spec = ModelInputSpec(target_size=(640, 640))
        result = normalize_spatial(unit, spec, PayloadFormat.UINT8_RGB)
        assert result.run_id == "test_run_123"

    def test_video_frame_is_decoded_before_normalization(self, tmp_path):
        video_path = tmp_path / "sample.avi"
        writer = cv2.VideoWriter(
            str(video_path), cv2.VideoWriter_fourcc(*"MJPG"), 10.0, (64, 48)
        )
        writer.write(np.full((48, 64, 3), 127, dtype=np.uint8))
        writer.release()
        unit = VisualUnit(
            unit_id="frame_000000",
            source_type="video_frame",
            frame_index=0,
            width=64,
            height=48,
            path=str(video_path),
        )

        result = normalize_spatial(
            unit, ModelInputSpec(target_size=(64, 64)), PayloadFormat.UINT8_RGB
        )

        assert result.payload.shape == (64, 64, 3)


class TestPrepareModelInput:
    def test_output_tensor_shape(self, tmp_path):
        import torch
        unit = _make_visual_unit(tmp_path)
        spec = ModelInputSpec(target_size=(640, 640), resize_mode="letterbox")
        normalized = normalize_spatial(unit, spec, PayloadFormat.UINT8_RGB)
        tensor = prepare_model_input(normalized, spec, device="cpu")
        assert tensor.shape == (1, 3, 640, 640)  # (batch, C, H, W)
        assert tensor.dtype == torch.float32

    def test_output_values_normalized(self, tmp_path):
        unit = _make_visual_unit(tmp_path)
        spec = ModelInputSpec(
            target_size=(640, 640),
            mean=(0.0, 0.0, 0.0),
            std=(1.0, 1.0, 1.0),
        )
        normalized = normalize_spatial(unit, spec, PayloadFormat.UINT8_RGB)
        tensor = prepare_model_input(normalized, spec, device="cpu")
        # Con mean=0, std=1, los valores deben estar en [0, 1]
        assert tensor.min() >= 0.0
        assert tensor.max() <= 1.0


class TestDetectionNormalizerWithTransform:
    def test_box_reprojection_via_transform(self):
        from eovrt_media.contracts.detection import RawDetection
        from eovrt_media.postprocessing.detection_normalizer import DetectionNormalizer

        # Original: 800x600, modelo ve: 640x640 (letterbox scale=0.8, pad_y=160)
        transform = ResizeTransform(scale_x=0.8, scale_y=0.8, pad_x=0.0, pad_y=160.0)
        # Caja en espacio modelo: [160, 288, 480, 448]
        raw = [RawDetection(label="person", score=0.9, box_xyxy=[160.0, 288.0, 480.0, 448.0])]
        normalizer = DetectionNormalizer(min_confidence=0.0, min_box_area_px=0.0)
        detections = normalizer.normalize(
            raw_detections=raw,
            width=800,
            height=600,
            model_name="mock",
            transform=transform,
        )
        assert len(detections) == 1
        x1, y1, x2, y2 = detections[0].bbox_xyxy
        # (160-0)/0.8=200, (288-160)/0.8=160, (480-0)/0.8=600, (448-160)/0.8=360
        assert x1 == pytest.approx(200.0, abs=1.0)
        assert y1 == pytest.approx(160.0, abs=1.0)
        assert x2 == pytest.approx(600.0, abs=1.0)
        assert y2 == pytest.approx(360.0, abs=1.0)

    def test_no_transform_keeps_existing_behavior(self):
        from eovrt_media.contracts.detection import RawDetection
        from eovrt_media.postprocessing.detection_normalizer import DetectionNormalizer

        raw = [RawDetection(label="person", score=0.9, box_xyxy=[100.0, 50.0, 300.0, 250.0])]
        normalizer = DetectionNormalizer(min_confidence=0.0, min_box_area_px=0.0)
        detections = normalizer.normalize(raw, width=640, height=480, model_name="mock")
        assert detections[0].bbox_xyxy == [100.0, 50.0, 300.0, 250.0]
