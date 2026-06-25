"""Tests for previews rendered directly from normalized payloads."""

from __future__ import annotations

import cv2
import numpy as np
import pytest

from eovrt_media.contracts import Detection
from eovrt_media.visualize import draw_detections_rgb


def _detection() -> Detection:
    return Detection(
        label="person",
        confidence=0.9,
        bbox_xyxy=[1.0, 1.0, 6.0, 6.0],
        bbox_norm_xyxy=[0.1, 0.1, 0.6, 0.6],
    )


@pytest.mark.parametrize(
    ("payload", "expected_bgr"),
    [
        (np.full((10, 10, 3), [255, 0, 0], dtype=np.uint8), [0, 0, 255]),
        (np.full((10, 10, 3), [1.0, 0.0, 0.0], dtype=np.float16), [0, 0, 255]),
    ],
)
def test_draw_detections_rgb_writes_rgb_uint8_and_float_payloads(
    tmp_path, payload, expected_bgr
):
    output_path = tmp_path / "nested" / "preview.jpg"

    draw_detections_rgb(payload, [_detection()], output_path)

    rendered = cv2.imread(str(output_path))
    assert rendered is not None
    assert np.allclose(rendered[9, 9], expected_bgr, atol=5)

