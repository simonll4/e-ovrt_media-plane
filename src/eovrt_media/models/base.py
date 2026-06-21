"""Interfaz base para adaptadores de modelo OVD."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from PIL import Image

from eovrt_media.contracts.detection import RawDetection


@dataclass
class ModelInputSpec:
    """Especificación de preprocesamiento de imagen requerida por el modelo."""

    target_size: tuple[int, int]
    """(H, W) objetivo para el Normalizer."""

    resize_mode: str = "letterbox"
    """Estrategia de redimensionado: "letterbox" | "bilinear"."""

    channel_order: str = "rgb"
    """Orden de canales esperado por el modelo."""

    mean: tuple[float, float, float] = (0.485, 0.456, 0.406)
    """Media de normalización por canal (RGB)."""

    std: tuple[float, float, float] = (0.229, 0.224, 0.225)
    """Desviación estándar de normalización por canal (RGB)."""

    dtype: str = "float32"
    """Tipo de dato del tensor de entrada."""


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

    @property
    @abstractmethod
    def input_spec(self) -> ModelInputSpec:
        """Especificación de preprocesamiento requerida por el modelo."""

    def close(self) -> None:
        """Liberar recursos del modelo (opcional)."""
