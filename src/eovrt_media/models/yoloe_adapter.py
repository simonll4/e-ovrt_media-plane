"""Adaptador de YOLOE usando Ultralytics."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from PIL import Image

from eovrt_media.contracts.detection import RawDetection
from eovrt_media.contracts.normalized_unit import NormalizedUnit
from eovrt_media.models.base import BaseDetectorAdapter, ModelInputSpec
from eovrt_media.config.prompt_plan import PromptPlan
from eovrt_media.models.runtime_utils import (
    make_warmup_image,
    resolve_device,
    should_use_half,
)
from eovrt_media.preprocessing import prepare_model_input

if TYPE_CHECKING:
    import torch

logger = logging.getLogger(__name__)


class YOLOEUltralyticsAdapter(BaseDetectorAdapter):
    """Adaptador para YOLOE via Ultralytics."""

    PROMPT_BACKEND = "yoloe"

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
            self.predict(dummy, PromptPlan.from_texts(["object"], "yoloe"))

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

    def _ensure_classes(self, plan: PromptPlan) -> None:
        """Configura las clases del modelo si las frases del plan cambiaron."""
        texts = plan.texts()
        if self._prompts_set != texts:
            logger.info(f"Configurando clases YOLOE: {texts}")
            use_half = should_use_half(self.device, self.half_precision)
            if use_half:
                # set_classes corre el text encoder (reprta) que requiere fp32;
                # si el modelo ya está en fp16 (por predict anterior) revertimos,
                # luego volvemos a half y casteamos pe explícitamente
                self.model.model.float()
            self.model.set_classes(texts)
            self._prompts_set = list(texts)
            if use_half:
                self.model.model.half()
                pe = getattr(self.model.model, "pe", None)
                if pe is not None:
                    self.model.model.pe = pe.half()

    def predict(
        self, image: Image.Image | Path | torch.Tensor, plan: PromptPlan
    ) -> list[RawDetection]:
        """Ejecuta inferencia con YOLOE.

        Args:
            image: Imagen PIL o ruta a archivo.
            plan: PromptPlan resuelto; ``set_classes(plan.texts())`` fija el orden.

        Returns:
            Lista de RawDetection ligadas al plan, con boxes en píxeles.
        """
        if self.model is None:
            raise RuntimeError("Modelo no cargado. Llamar load() primero.")

        # Asegurar clases configuradas
        self._ensure_classes(plan)

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
        if result.boxes is None:
            return []
        boxes = result.boxes.xyxy.cpu().tolist()
        scores = result.boxes.conf.cpu().tolist()
        class_ids = result.boxes.cls.cpu().tolist()
        return self._decode_boxes(boxes, scores, class_ids, plan)

    def _decode_boxes(self, boxes, scores, class_ids, plan: PromptPlan) -> list[RawDetection]:
        """Liga cada caja a su frase: el class_id es el índice directo en el plan."""
        by_index = plan.by_index()
        detections = []
        for box, score, cls_id in zip(boxes, scores, class_ids):
            idx = int(cls_id)
            if idx < 0 or idx >= len(by_index):
                # Defensa: el modelo no debería devolver un class_id fuera del
                # rango de set_classes(plan.texts()); si pasa, se descarta + log.
                logger.warning(
                    "YOLOE devolvió class_id=%s fuera de rango (0..%d); detección descartada.",
                    idx,
                    len(by_index) - 1,
                )
                continue
            phrase = by_index[idx]
            detections.append(
                RawDetection(
                    label=phrase.canonical,
                    prompt_id=phrase.prompt_id,
                    source_prompt=phrase.text,
                    strategy=phrase.strategy,
                    condition_id=phrase.condition_id,
                    score=float(score),
                    box_xyxy=[float(c) for c in box],
                )
            )
        return detections

    def forward(self, unit: NormalizedUnit, plan: PromptPlan) -> list[RawDetection]:
        """Ejecuta la inferencia desde el payload normalizado del canal."""
        return self.predict(prepare_model_input(unit, self.input_spec, self.device), plan)

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
