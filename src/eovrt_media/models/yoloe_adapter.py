"""Adaptador de YOLOE usando Ultralytics."""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
from PIL import Image

from eovrt_media.contracts.detection import RawDetection
from eovrt_media.contracts.normalized_unit import NormalizedUnit
from eovrt_media.models.base import BaseDetectorAdapter, ModelInputSpec
from eovrt_media.models.runtime_utils import (
    make_warmup_image,
    resolve_device,
    should_use_half,
)

logger = logging.getLogger(__name__)


class YOLOEUltralyticsAdapter(BaseDetectorAdapter):
    """Adaptador para YOLOE via Ultralytics."""

    def __init__(
        self,
        weights: str = "yoloe-26s-seg.pt",
        device: str = "cpu",
        confidence_threshold: float = 0.25,
        iou_threshold: float = 0.50,
        image_size: int | list[int] | None = None,
        half_precision: bool = False,
        warmup: bool = False,
    ) -> None:
        self.weights = weights
        self.device = device
        self.confidence_threshold = confidence_threshold
        self.iou_threshold = iou_threshold
        self.image_size = image_size
        self.half_precision = half_precision
        self.warmup = warmup
        self.model = None
        self._prompts_set: list[str] | None = None

    def load(self) -> None:
        """Carga el modelo YOLOE desde el checkpoint."""
        from ultralytics import YOLOE

        self.device = resolve_device(self.device)
        logger.info(f"Cargando YOLOE desde: {self.weights} → {self.device}")
        self.model = YOLOE(self.weights)

        if should_use_half(self.device, self.half_precision):
            self._patch_process_mask_for_fp16()

        if self.warmup:
            dummy = Image.fromarray(make_warmup_image((640, 640)))
            self.predict(dummy, ["object"])

        logger.info("YOLOE cargado correctamente.")

    @staticmethod
    def _patch_process_mask_for_fp16() -> None:
        # Ultralytics process_mask hace protos.float() explícitamente, causando
        # mismatch cuando masks_in llega en fp16. Casteamos masks_in a fp32 para
        # que ambos operandos coincidan. Solo se aplica al proceso de máscaras;
        # la inferencia principal sigue en fp16.
        import ultralytics.utils.ops as ops_module
        _orig = ops_module.process_mask

        def _process_mask_fp16_safe(protos, masks_in, bboxes, shape, upsample=False):
            return _orig(protos, masks_in.float(), bboxes, shape, upsample)

        ops_module.process_mask = _process_mask_fp16_safe

    def _ensure_classes(self, prompts: list[str]) -> None:
        """Configura las clases del modelo si los prompts cambiaron."""
        if self._prompts_set != prompts:
            logger.info(f"Configurando clases YOLOE: {prompts}")
            use_half = should_use_half(self.device, self.half_precision)
            if use_half:
                # set_classes corre el text encoder (reprta) que requiere fp32;
                # si el modelo ya está en fp16 (por predict anterior) revertimos,
                # luego volvemos a half y casteamos pe explícitamente
                self.model.model.float()
            self.model.set_classes(prompts)
            self._prompts_set = list(prompts)
            if use_half:
                self.model.model.half()
                pe = getattr(self.model.model, "pe", None)
                if pe is not None:
                    self.model.model.pe = pe.half()

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

        predict_kwargs = {
            "source": source,
            "conf": self.confidence_threshold,
            "iou": self.iou_threshold,
            "device": self.device,
            "verbose": False,
            "half": should_use_half(self.device, self.half_precision),
        }
        if self.image_size is not None:
            predict_kwargs["imgsz"] = self.image_size

        results = self.model.predict(**predict_kwargs)

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

    def forward(self, unit: NormalizedUnit, prompts: list[str]) -> list[RawDetection]:
        """Ejecuta la inferencia desde el payload normalizado del canal."""
        payload = unit.payload
        if payload.dtype != np.uint8:
            payload = np.clip(payload * 255.0, 0, 255).astype(np.uint8)
        return self.predict(Image.fromarray(payload), prompts)

    @property
    def input_spec(self) -> ModelInputSpec:
        """Especificación de preprocesamiento de YOLOE (640x640 letterbox, sin normalización)."""
        size = self.image_size if isinstance(self.image_size, int) else 640
        return ModelInputSpec(
            target_size=(size, size),
            resize_mode="letterbox",
            mean=(0.0, 0.0, 0.0),
            std=(1.0, 1.0, 1.0),
        )

    def close(self) -> None:
        """Libera el modelo."""
        self.model = None
        self._prompts_set = None
