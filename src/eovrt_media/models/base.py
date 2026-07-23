"""Interfaz base para adaptadores de modelo OVD."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING
from PIL import Image

from eovrt_media.contracts.detection import RawDetection

if TYPE_CHECKING:
    from eovrt_media.contracts.normalized_unit import NormalizedUnit
    from eovrt_media.config.prompt_plan import PromptPlan


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

    PROMPT_BACKEND: str = "default"
    """Clave de fraseo del adaptador: 'gdino' | 'yoloe' | 'default'."""

    @abstractmethod
    def load(self) -> None:
        """Cargar el modelo en memoria/GPU."""

    @abstractmethod
    def predict(self, image: Image.Image | Path, plan: PromptPlan) -> list[RawDetection]:
        """Ejecutar inferencia sobre una imagen con el plan de prompts dado.

        Args:
            image: Imagen PIL o ruta a archivo.
            plan: PromptPlan resuelto; el adaptador liga cada detección a su clase.

        Returns:
            Lista de detecciones crudas (RawDetection) ya ligadas al plan.
        """

    @abstractmethod
    def forward(self, unit: NormalizedUnit, plan: PromptPlan) -> list[RawDetection]:
        """Ejecutar inferencia desde una unidad normalizada del canal."""

    @property
    @abstractmethod
    def input_spec(self) -> ModelInputSpec:
        """Especificación de preprocesamiento requerida por el modelo."""

    def prepare_run(self, plan: PromptPlan) -> None:
        """Pre-flight por corrida: una inferencia dummy con el plan REAL.

        Mueve los costos lazy del primer frame (set_classes de YOLOE ~1.1 s,
        autotune de kernels CUDA ~3 s en el primer run del proceso) a ANTES de
        que la fuente empiece a producir; sin esto, una fuente viva dropea
        decenas de frames por queue_full durante la primera inferencia
        (docs/operacion/61 del repo docs). El warmup de load() no alcanza:
        corre con un plan dummy, y el binding es por-plan.
        """
        from eovrt_media.models.runtime_utils import make_warmup_image

        dummy = Image.fromarray(make_warmup_image(self.input_spec.target_size))
        self.predict(dummy, plan)

    def close(self) -> None:
        """Liberar recursos del modelo (opcional)."""
