"""Visualización de detecciones — previews anotadas con bounding boxes."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

import cv2
import numpy as np

from eovrt_media.contracts import Detection, RawDetection

if TYPE_CHECKING:
    from eovrt_media.contracts.normalized_unit import ResizeTransform

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


def annotate_payload_bgr(
    image_rgb: np.ndarray,
    detections: list[Detection | RawDetection],
) -> np.ndarray:
    """Convierte un payload RGB (uint8 o float normalizado) a BGR anotado.

    Devuelve un array BGR uint8 con las detecciones dibujadas. Reutilizado tanto por las
    previews JPG como por el escritor de video anotado.
    """
    rgb = np.asarray(image_rgb)
    if rgb.ndim != 3 or rgb.shape[2] != 3:
        raise ValueError("El payload para preview debe tener forma HxWx3 RGB")
    if np.issubdtype(rgb.dtype, np.floating):
        rgb = np.clip(rgb, 0.0, 1.0) * 255.0
    rgb_uint8 = np.clip(rgb, 0, 255).astype(np.uint8)
    image_bgr = cv2.cvtColor(rgb_uint8, cv2.COLOR_RGB2BGR)
    _draw_annotations(image_bgr, detections)
    return image_bgr


def deletterbox_bgr(
    image_bgr: np.ndarray,
    transform: "ResizeTransform",
    orig_width: int,
    orig_height: int,
    max_long_side: int = 960,
) -> np.ndarray:
    """Recorta el padding de letterbox y devuelve la imagen en el aspecto del
    frame ORIGINAL.

    El payload normalizado vive en espacio model-input (letterboxed cuadrado o
    stretch), pero `bbox_norm_xyxy` está normalizado al frame original. Al
    des-letterboxear, la preview pasa a compartir el sistema de coordenadas del
    frame original y `norm * ancho/alto` mapea linealmente. Model-agnóstico:
    sirve para letterbox (pad>0, escala uniforme) y stretch (pad=0, escalas
    distintas). El lado largo se limita a `max_long_side` para acotar el JPG.
    """
    new_w = max(1, round(orig_width * transform.scale_x))
    new_h = max(1, round(orig_height * transform.scale_y))
    px = max(0, int(round(transform.pad_x)))
    py = max(0, int(round(transform.pad_y)))
    content = image_bgr[py : py + new_h, px : px + new_w]
    if content.size == 0:
        return image_bgr
    if orig_width >= orig_height:
        out_w = min(int(orig_width), max_long_side)
        out_h = max(1, round(out_w * orig_height / orig_width))
    else:
        out_h = min(int(orig_height), max_long_side)
        out_w = max(1, round(out_h * orig_width / orig_height))
    return cv2.resize(content, (out_w, out_h), interpolation=cv2.INTER_LINEAR)


def draw_detections_rgb(
    image_rgb: np.ndarray,
    detections: list[Detection | RawDetection],
    output_path: str | Path,
    *,
    transform: "ResizeTransform | None" = None,
    orig_size: tuple[int, int] | None = None,
) -> None:
    """Anota y guarda un payload RGB uint8 o de punto flotante normalizado.

    Si se pasan `transform` y `orig_size` (ancho, alto del frame original), la
    preview se des-letterboxea al aspecto del frame original (ver
    `deletterbox_bgr`), de modo que un overlay que use `bbox_norm_xyxy` calce
    sobre la imagen y no queden barras negras.
    """
    image_bgr = annotate_payload_bgr(image_rgb, detections)
    if transform is not None and orig_size is not None:
        image_bgr = deletterbox_bgr(image_bgr, transform, orig_size[0], orig_size[1])
    _write_preview(image_bgr, output_path)
