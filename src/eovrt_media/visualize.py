"""Visualización de detecciones — previews anotadas con bounding boxes."""

from __future__ import annotations

import logging
from pathlib import Path

import cv2
import numpy as np

from eovrt_media.contracts import Detection, RawDetection

logger = logging.getLogger(__name__)

# Paleta de colores para diferentes labels
_COLORS = [
    (0, 255, 0),     # verde
    (255, 0, 0),     # azul (BGR)
    (0, 0, 255),     # rojo (BGR)
    (255, 255, 0),   # cyan
    (0, 255, 255),   # amarillo
    (255, 0, 255),   # magenta
    (128, 255, 0),   # verde claro
    (255, 128, 0),   # azul claro
]


def _get_color(label: str) -> tuple[int, int, int]:
    """Devuelve un color consistente para un label dado."""
    idx = hash(label) % len(_COLORS)
    return _COLORS[idx]


def _draw_annotations(
    image_bgr: np.ndarray, detections: list[Detection | RawDetection]
) -> None:
    """Dibuja detecciones de espacio de píxeles sobre una imagen BGR."""
    for det in detections:
        color = _get_color(det.label)
        x1, y1, x2, y2 = [int(c) for c in det.bbox_xyxy]
        confidence = det.confidence if isinstance(det, Detection) else det.score

        cv2.rectangle(image_bgr, (x1, y1), (x2, y2), color, 2)

        label_text = f"{det.label} {confidence:.2f}"
        font = cv2.FONT_HERSHEY_SIMPLEX
        font_scale = 0.5
        thickness = 1
        (text_w, text_h), baseline = cv2.getTextSize(label_text, font, font_scale, thickness)

        cv2.rectangle(
            image_bgr,
            (x1, y1 - text_h - baseline - 4),
            (x1 + text_w, y1),
            color,
            cv2.FILLED,
        )
        cv2.putText(
            image_bgr,
            label_text,
            (x1, y1 - baseline - 2),
            font,
            font_scale,
            (0, 0, 0),
            thickness,
        )


def _write_preview(image_bgr: np.ndarray, output_path: str | Path) -> None:
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if not cv2.imwrite(str(output_path), image_bgr):
        raise OSError(f"No se pudo escribir preview: {output_path}")
    logger.debug(f"Preview guardada: {output_path}")


def draw_detections(
    image_path: str | Path,
    detections: list[Detection],
    output_path: str | Path,
) -> None:
    """Dibuja bounding boxes y labels sobre una imagen de disco y la guarda."""
    image_bgr = cv2.imread(str(image_path))
    if image_bgr is None:
        logger.error(f"No se pudo leer imagen para preview: {image_path}")
        return
    _draw_annotations(image_bgr, detections)
    _write_preview(image_bgr, output_path)


def draw_detections_rgb(
    image_rgb: np.ndarray,
    detections: list[Detection | RawDetection],
    output_path: str | Path,
) -> None:
    """Anota y guarda un payload RGB uint8 o de punto flotante normalizado."""
    rgb = np.asarray(image_rgb)
    if rgb.ndim != 3 or rgb.shape[2] != 3:
        raise ValueError("El payload para preview debe tener forma HxWx3 RGB")
    if np.issubdtype(rgb.dtype, np.floating):
        rgb = np.clip(rgb, 0.0, 1.0) * 255.0
    rgb_uint8 = np.clip(rgb, 0, 255).astype(np.uint8)
    image_bgr = cv2.cvtColor(rgb_uint8, cv2.COLOR_RGB2BGR)
    _draw_annotations(image_bgr, detections)
    _write_preview(image_bgr, output_path)
