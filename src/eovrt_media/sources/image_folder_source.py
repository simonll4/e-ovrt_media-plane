"""Fuente de imágenes desde una carpeta local."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Iterator

import cv2

from eovrt_media.contracts import VisualUnit
from eovrt_media.sources.base import BaseSource

logger = logging.getLogger(__name__)


class ImageFolderSource(BaseSource):
    """Lee imágenes desde una carpeta local y produce VisualUnit por cada imagen.

    Parámetros:
        folder_path: Ruta a la carpeta de imágenes.
        extensions: Extensiones de archivo soportadas (e.g., [".jpg", ".jpeg", ".png"]).
    """

    def __init__(self, folder_path: str | Path, extensions: list[str] | None = None) -> None:
        self.folder_path = Path(folder_path)
        self.extensions = [ext.lower() for ext in (extensions or [".jpg", ".jpeg", ".png"])]

        if not self.folder_path.exists():
            raise FileNotFoundError(f"Carpeta de imágenes no encontrada: {self.folder_path}")
        if not self.folder_path.is_dir():
            raise NotADirectoryError(f"La ruta no es un directorio: {self.folder_path}")

    def _list_image_files(self) -> list[Path]:
        """Lista archivos de imagen ordenados alfabéticamente."""
        files = []
        for path in sorted(self.folder_path.iterdir()):
            if path.is_file() and path.suffix.lower() in self.extensions:
                files.append(path)
        return files

    def _create_visual_unit(self, image_path: Path, index: int) -> VisualUnit:
        """Crea un VisualUnit a partir de un archivo de imagen."""
        # Leer dimensiones sin cargar toda la imagen en memoria
        img = cv2.imread(str(image_path))
        if img is None:
            raise ValueError(f"No se pudo leer la imagen: {image_path}")

        height, width = img.shape[:2]

        unit_id = f"img_{index:06d}"
        return VisualUnit(
            unit_id=unit_id,
            source_path=str(image_path),
            source_type="image",
            frame_index=None,
            width=width,
            height=height,
            timestamp_ms=None,
        )

    def __iter__(self) -> Iterator[VisualUnit]:
        """Itera sobre las imágenes de la carpeta produciendo VisualUnit."""
        files = self._list_image_files()
        if not files:
            logger.warning(f"No se encontraron imágenes en: {self.folder_path}")
            return

        logger.info(f"Encontradas {len(files)} imágenes en {self.folder_path}")
        for index, path in enumerate(files):
            try:
                yield self._create_visual_unit(path, index)
            except ValueError as e:
                logger.error(f"Error leyendo imagen {path}: {e}")
                continue

    def __len__(self) -> int:
        """Retorna la cantidad de imágenes encontradas."""
        return len(self._list_image_files())
