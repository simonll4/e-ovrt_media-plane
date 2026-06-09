"""Interfaz base para adaptadores de modelo OVD."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from PIL import Image

from eovrt_media.contracts.detection import RawDetection


class BaseDetectorAdapter(ABC):
    """Interfaz común para todos los adaptadores de modelo."""

    @abstractmethod
    def load(self) -> None:
        """Cargar el modelo en memoria/GPU."""

    @abstractmethod
    def predict(self, image: Image.Image | Path, prompts: list[str]) -> list[RawDetection]:
        """Ejecutar inferencia sobre una imagen con los prompts dados.

        Args:
            image: Imagen PIL o ruta a archivo.
            prompts: Lista de textos de prompts a detectar.

        Returns:
            Lista de detecciones crudas (RawDetection).
        """

    def close(self) -> None:
        """Liberar recursos del modelo (opcional)."""
