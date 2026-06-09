"""Adaptador de YOLOE usando Ultralytics."""

from __future__ import annotations

import logging
from pathlib import Path

from PIL import Image

from eovrt_media.contracts.detection import RawDetection
from eovrt_media.models.base import BaseDetectorAdapter

logger = logging.getLogger(__name__)


class YOLOEUltralyticsAdapter(BaseDetectorAdapter):
    """Adaptador para YOLOE via Ultralytics."""

    def __init__(
        self,
        weights: str = "yoloe-26s-seg.pt",
        device: str = "cpu",
        confidence_threshold: float = 0.25,
        iou_threshold: float = 0.50,
    ) -> None:
        self.weights = weights
        self.device = device
        self.confidence_threshold = confidence_threshold
        self.iou_threshold = iou_threshold
        self.model = None
        self._prompts_set: list[str] | None = None

    def load(self) -> None:
        """Carga el modelo YOLOE desde el checkpoint."""
        from ultralytics import YOLOE

        logger.info(f"Cargando YOLOE desde: {self.weights} → {self.device}")
        self.model = YOLOE(self.weights)
        logger.info("YOLOE cargado correctamente.")

    def _ensure_classes(self, prompts: list[str]) -> None:
        """Configura las clases del modelo si los prompts cambiaron."""
        if self._prompts_set != prompts:
            logger.info(f"Configurando clases YOLOE: {prompts}")
            self.model.set_classes(prompts)
            self._prompts_set = list(prompts)

    def predict(self, image: Image.Image | Path, prompts: list[str]) -> list[RawDetection]:
        """Ejecuta inferencia con YOLOE.

        Args:
            image: Imagen PIL o ruta a archivo.
            prompts: Lista de textos de prompts.

        Returns:
            Lista de RawDetection con bounding boxes en píxeles.
        """
        if self.model is None:
            raise RuntimeError("Modelo no cargado. Llamar load() primero.")

        # Asegurar clases configuradas
        self._ensure_classes(prompts)

        # YOLOE acepta tanto paths como PIL images
        source = str(image) if isinstance(image, Path) else image

        results = self.model.predict(
            source=source,
            conf=self.confidence_threshold,
            iou=self.iou_threshold,
            device=self.device,
            verbose=False,
        )

        if not results:
            return []

        result = results[0]
        detections = []

        if result.boxes is not None:
            boxes = result.boxes.xyxy.cpu().tolist()
            scores = result.boxes.conf.cpu().tolist()
            class_ids = result.boxes.cls.cpu().tolist()
            names = result.names  # dict: {class_id: name}

            for box, score, cls_id in zip(boxes, scores, class_ids):
                label = names.get(int(cls_id), f"class_{int(cls_id)}")
                detections.append(
                    RawDetection(
                        label=label,
                        score=float(score),
                        box_xyxy=[float(c) for c in box],
                    )
                )

        return detections

    def close(self) -> None:
        """Libera el modelo."""
        self.model = None
        self._prompts_set = None
