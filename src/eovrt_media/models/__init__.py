"""Módulo de adaptadores de modelos del plano de medios E-OVRT."""

from __future__ import annotations

from typing import TYPE_CHECKING

from eovrt_media.models.base import BaseDetectorAdapter
from eovrt_media.models.mock_detector import MockDetectorAdapter
from eovrt_media.models.grounding_dino_adapter import GroundingDinoHFAdapter
from eovrt_media.models.yoloe_adapter import YOLOEUltralyticsAdapter

if TYPE_CHECKING:
    from eovrt_media.config import ModelSection


def create_adapter(model_config: ModelSection) -> BaseDetectorAdapter:
    """Crea un adaptador de modelo según la configuración de corrida.

    Args:
        model_config: Sección 'model' de la configuración.

    Returns:
        Instancia del adaptador correspondiente (sin cargar pesos aún).
    """
    adapter_name = model_config.adapter or model_config.name

    if not adapter_name:
        raise ValueError("No se especificó 'adapter' o 'name' en la configuración del modelo.")

    adapter_name = adapter_name.lower().strip()

    if adapter_name == "mock":
        return MockDetectorAdapter()

    elif adapter_name in ("grounding_dino", "grounding_dino_hf"):
        return GroundingDinoHFAdapter(
            model_id=model_config.model_id or "IDEA-Research/grounding-dino-tiny",
            device=model_config.device,
            box_threshold=model_config.box_threshold,
            text_threshold=model_config.text_threshold,
            local_dir=model_config.local_dir,
            half_precision=model_config.runtime.half_precision,
            warmup=model_config.runtime.warmup,
        )

    elif adapter_name in ("yoloe", "yoloe_ultralytics"):
        return YOLOEUltralyticsAdapter(
            weights=model_config.weights or "yoloe-26s-seg.pt",
            device=model_config.device,
            confidence_threshold=model_config.confidence_threshold,
            iou_threshold=model_config.iou_threshold,
            image_size=model_config.image_size,
            half_precision=model_config.runtime.half_precision,
            warmup=model_config.runtime.warmup,
        )

    else:
        raise ValueError(
            f"Adaptador '{adapter_name}' no soportado. "
            f"Opciones: mock, grounding_dino, yoloe"
        )


__all__ = [
    "BaseDetectorAdapter",
    "MockDetectorAdapter",
    "GroundingDinoHFAdapter",
    "YOLOEUltralyticsAdapter",
    "create_adapter",
]
