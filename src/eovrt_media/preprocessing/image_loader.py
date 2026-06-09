"""Cargador de imágenes para diferentes tipos de fuentes visuales."""

from __future__ import annotations

import cv2
from PIL import Image
from eovrt_media.contracts import VisualUnit


def load_image(unit: VisualUnit) -> Image.Image:
    """Carga la imagen correspondiente a una unidad visual.

    Soporta carga desde archivo directo de imagen o extracción de un
    frame específico de un archivo de video.

    Args:
        unit: Instancia de VisualUnit.

    Returns:
        Imagen cargada como PIL.Image (RGB).
    """
    path_str = unit.path or unit.source_path
    if not path_str:
        raise ValueError(f"No se especificó ruta de archivo en VisualUnit: {unit.unit_id}")

    if unit.source_type == "video_frame":
        if unit.frame_index is None:
            raise ValueError(
                f"La unidad visual es de tipo 'video_frame' pero no tiene 'frame_index': {unit.unit_id}"
            )
            
        cap = cv2.VideoCapture(path_str)
        if not cap.isOpened():
            raise ValueError(f"No se pudo abrir el archivo de video: {path_str}")

        try:
            cap.set(cv2.CAP_PROP_POS_FRAMES, unit.frame_index)
            ret, frame = cap.read()
            if not ret:
                raise ValueError(
                    f"No se pudo leer el frame {unit.frame_index} del video: {path_str}"
                )
            
            # Convertir BGR a RGB
            frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            return Image.fromarray(frame_rgb)
        finally:
            cap.release()
    else:
        # Carga normal de imagen
        return Image.open(path_str).convert("RGB")
