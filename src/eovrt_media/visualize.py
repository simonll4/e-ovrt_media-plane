"""Visualización de detecciones — previews anotadas con bounding boxes."""

from __future__ import annotations

import logging
from pathlib import Path

import cv2

from eovrt_media.contracts import Detection

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


def draw_detections(
    image_path: str | Path,
    detections: list[Detection],
    output_path: str | Path,
) -> None:
    """Dibuja bounding boxes y labels sobre una imagen y guarda el resultado.

    Args:
        image_path: Ruta a la imagen original.
        detections: Lista de detecciones a dibujar.
        output_path: Ruta donde guardar la imagen anotada.
    """
    img = cv2.imread(str(image_path))
    if img is None:
        logger.error(f"No se pudo leer imagen para preview: {image_path}")
        return

    for det in detections:
        color = _get_color(det.label)
        x1, y1, x2, y2 = [int(c) for c in det.bbox_xyxy]

        # Bounding box
        cv2.rectangle(img, (x1, y1), (x2, y2), color, 2)

        # Label con fondo
        label_text = f"{det.label} {det.confidence:.2f}"
        font = cv2.FONT_HERSHEY_SIMPLEX
        font_scale = 0.5
        thickness = 1
        (text_w, text_h), baseline = cv2.getTextSize(label_text, font, font_scale, thickness)

        # Fondo del texto
        cv2.rectangle(
            img,
            (x1, y1 - text_h - baseline - 4),
            (x1 + text_w, y1),
            color,
            cv2.FILLED,
        )

        # Texto
        cv2.putText(
            img,
            label_text,
            (x1, y1 - baseline - 2),
            font,
            font_scale,
            (0, 0, 0),  # negro
            thickness,
        )

    # Guardar
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(output_path), img)
    logger.debug(f"Preview guardada: {output_path}")
