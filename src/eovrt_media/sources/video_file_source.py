"""Fuente de video local con muestreo de frames."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Iterator

import cv2

from eovrt_media.contracts import VisualUnit
from eovrt_media.sources.base import BaseSource

logger = logging.getLogger(__name__)


class VideoFileSource(BaseSource):
    """Lee un archivo de video y produce VisualUnits con muestreo de frames.

    Parámetros:
        video_path: Ruta al archivo de video.
        every_n: Procesar un frame cada N frames.
        target_fps: FPS objetivo para el procesamiento (si se define, ignora every_n).
        max_units: Límite máximo de frames a procesar.
    """

    def __init__(
        self,
        video_path: str | Path,
        every_n: int = 1,
        target_fps: float | None = None,
        max_units: int | None = None,
    ) -> None:
        self.video_path = Path(video_path)
        if not self.video_path.exists():
            raise FileNotFoundError(f"Archivo de video no encontrado: {self.video_path}")

        self.every_n = every_n
        self.target_fps = target_fps
        self.max_units = max_units

        # Obtener metadatos del video
        cap = cv2.VideoCapture(str(self.video_path))
        if not cap.isOpened():
            raise ValueError(f"No se pudo abrir el archivo de video: {self.video_path}")

        self.fps = cap.get(cv2.CAP_PROP_FPS)
        self.total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        self.width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        self.height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        cap.release()

        logger.info(
            f"Video cargado: {self.video_path.name} | {self.width}x{self.height} | "
            f"{self.fps:.2f} FPS | {self.total_frames} frames totales"
        )

    def _get_frame_indices(self) -> list[int]:
        """Calcula los índices de los frames que deben ser procesados."""
        if self.target_fps is not None and self.fps > 0:
            # Muestrear por FPS objetivo
            step = self.fps / self.target_fps
            indices = []
            curr = 0.0
            while curr < self.total_frames:
                indices.append(int(round(curr)))
                curr += step
        else:
            # Muestrear cada N frames
            step = max(1, self.every_n)
            indices = list(range(0, self.total_frames, step))

        # Aplicar límite máximo
        if self.max_units is not None:
            indices = indices[:self.max_units]

        return indices

    def __iter__(self) -> Iterator[VisualUnit]:
        """Itera sobre la fuente de video produciendo VisualUnits."""
        indices = self._get_frame_indices()
        if not indices:
            logger.warning(f"No se seleccionaron frames para procesar en: {self.video_path}")
            return

        logger.info(f"Procesando {len(indices)} frames del video: {self.video_path.name}")
        for i, frame_idx in enumerate(indices):
            # Calcular timestamp estimado en base a FPS
            timestamp_ms = (frame_idx / self.fps) * 1000.0 if self.fps > 0 else 0.0
            unit_id = f"frame_{i:06d}"
            
            yield VisualUnit(
                unit_id=unit_id,
                source_path=str(self.video_path),
                source_type="video_frame",
                frame_index=frame_idx,
                width=self.width,
                height=self.height,
                timestamp_ms=round(timestamp_ms, 2),
            )

    def __len__(self) -> int:
        """Devuelve la cantidad de frames a procesar después del muestreo."""
        return len(self._get_frame_indices())
