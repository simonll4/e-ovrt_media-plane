"""Cargador de imágenes para diferentes tipos de fuentes visuales."""

from __future__ import annotations

import cv2
import numpy as np
from PIL import Image
from eovrt_media.contracts import VisualUnit


def _resolve_path(unit: VisualUnit) -> str:
    path_str = unit.path or unit.source_path
    if not path_str:
        raise ValueError(f"No se especificó ruta de archivo en VisualUnit: {unit.unit_id}")
    return path_str


def _read_video_frame_bgr(unit: VisualUnit, path_str: str) -> np.ndarray:
    """Extrae por índice un frame BGR de un archivo de video."""
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
        return frame
    finally:
        cap.release()


def load_image_array(unit: VisualUnit) -> np.ndarray:
    """Carga la unidad visual como ndarray RGB, sin pasar por PIL.

    Es el camino del hilo productor: `normalize_spatial` sólo necesita el
    ndarray, y envolverlo en un `PIL.Image` para desenvolverlo acto seguido
    cuesta dos copias completas del frame en Python —con el GIL tomado— por
    unidad procesada (doc 73 §9.2). Sólo la rama de archivo de imagen sigue
    decodificando con PIL, que es donde PIL realmente hace falta.

    Args:
        unit: Instancia de VisualUnit.

    Returns:
        Imagen como ndarray RGB (uint8, HxWx3).
    """
    # Fuentes vivas (OAK-D/RTSP) embeben el frame capturado para no reabrir el stream.
    if unit.pixel_data is not None:
        return cv2.cvtColor(np.asarray(unit.pixel_data), cv2.COLOR_BGR2RGB)

    path_str = _resolve_path(unit)

    if unit.source_type == "video_frame":
        return cv2.cvtColor(_read_video_frame_bgr(unit, path_str), cv2.COLOR_BGR2RGB)

    return np.asarray(Image.open(path_str).convert("RGB"))


def load_image(unit: VisualUnit) -> Image.Image:
    """Carga la imagen correspondiente a una unidad visual.

    Si ``unit.pixel_data`` está presente (frame BGR capturado por fuentes vivas
    como RtspSource), lo convierte directamente sin reabrir la fuente.
    En caso contrario carga desde disco o archivo de video por ruta.

    El pipeline usa `load_image_array`; esta variante se conserva para los
    consumidores que sí quieren un `PIL.Image`.

    Args:
        unit: Instancia de VisualUnit.

    Returns:
        Imagen cargada como PIL.Image (RGB).
    """
    if unit.pixel_data is not None:
        frame_bgr = np.asarray(unit.pixel_data)
        return Image.fromarray(cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB))

    path_str = _resolve_path(unit)

    if unit.source_type == "video_frame":
        frame_rgb = cv2.cvtColor(_read_video_frame_bgr(unit, path_str), cv2.COLOR_BGR2RGB)
        return Image.fromarray(frame_rgb)

    return Image.open(path_str).convert("RGB")
