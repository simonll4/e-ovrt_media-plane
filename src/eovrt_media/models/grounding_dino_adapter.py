"""Adaptador de Grounding DINO usando Hugging Face Transformers."""

from __future__ import annotations

import logging
import warnings
from pathlib import Path

import torch
from PIL import Image
from transformers import AutoModelForZeroShotObjectDetection, AutoProcessor

from eovrt_media.contracts.detection import RawDetection
from eovrt_media.models.base import BaseDetectorAdapter, ModelInputSpec

logger = logging.getLogger(__name__)


def _normalize_label(detected: str, prompts: list[str]) -> str:
    """Mapea un span parcial de GDINO al prompt original más cercano.

    GDINO hace matching de sub-spans del texto de entrada, por lo que puede
    devolver "visibility safety" en lugar del prompt completo "high visibility
    safety vest". Esta función busca el prompt cuyas palabras tienen mayor
    solapamiento con el span detectado.
    """
    detected_lower = detected.lower()
    for p in prompts:
        if p.lower() == detected_lower:
            return p
    for p in prompts:
        if detected_lower in p.lower():
            return p
    for p in prompts:
        if p.lower() in detected_lower:
            return p
    detected_words = set(detected_lower.split())
    return max(prompts, key=lambda p: len(detected_words & set(p.lower().split())))


class GroundingDinoHFAdapter(BaseDetectorAdapter):
    """Adaptador para Grounding DINO via Hugging Face Transformers.

    Usa AutoProcessor + AutoModelForZeroShotObjectDetection.
    """

    def __init__(
        self,
        model_id: str = "IDEA-Research/grounding-dino-tiny",
        device: str = "cpu",
        box_threshold: float = 0.35,
        text_threshold: float = 0.25,
        local_dir: str | None = None,
    ) -> None:
        self.model_id = model_id
        self.device = device
        self.box_threshold = box_threshold
        self.text_threshold = text_threshold
        self.local_dir = local_dir
        self.processor = None
        self.model = None

    def load(self) -> None:
        """Carga el processor y modelo en el dispositivo configurado."""
        source = self.local_dir if self.local_dir and Path(self.local_dir).exists() else self.model_id
        logger.info(f"Cargando Grounding DINO desde: {source} → {self.device}")

        self.processor = AutoProcessor.from_pretrained(source)
        self.model = AutoModelForZeroShotObjectDetection.from_pretrained(source).to(self.device)
        self.model.eval()

        logger.info("Grounding DINO cargado correctamente.")

    def predict(self, image: Image.Image | Path, prompts: list[str]) -> list[RawDetection]:
        """Ejecuta inferencia con Grounding DINO.

        Args:
            image: Imagen PIL o ruta a archivo.
            prompts: Lista de textos de prompts (e.g., ["person", "safety helmet"]).

        Returns:
            Lista de RawDetection con bounding boxes en píxeles.
        """
        if self.model is None or self.processor is None:
            raise RuntimeError("Modelo no cargado. Llamar load() primero.")

        # Asegurar que image es PIL
        if isinstance(image, Path):
            image = Image.open(image).convert("RGB")
        elif not isinstance(image, Image.Image):
            raise TypeError(f"Tipo de imagen no soportado: {type(image)}")

        # Construir texto para Grounding DINO: "prompt1. prompt2. prompt3."
        text = ". ".join(prompts) + "."

        inputs = self.processor(images=image, text=text, return_tensors="pt").to(self.device)

        with torch.no_grad():
            outputs = self.model(**inputs)

        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", category=FutureWarning, module="transformers")
            results = self.processor.post_process_grounded_object_detection(
                outputs,
                inputs.input_ids,
                threshold=self.box_threshold,
                text_threshold=self.text_threshold,
                target_sizes=[list(image.size[::-1])],  # [height, width]
            )[0]

        detections = []
        boxes = results["boxes"].cpu().tolist()
        scores = results["scores"].cpu().tolist()
        # text_labels is the stable key (labels will return int ids in transformers >=4.51)
        raw_labels = results.get("text_labels", results.get("labels", []))
        if hasattr(raw_labels, "tolist"):
            raw_labels = raw_labels.tolist()

        for box, score, label in zip(boxes, scores, raw_labels):
            normalized = _normalize_label(str(label).strip(), prompts)
            detections.append(
                RawDetection(
                    label=normalized,
                    score=float(score),
                    box_xyxy=[float(c) for c in box],
                )
            )

        return detections

    @property
    def input_spec(self) -> ModelInputSpec:
        """Especificación de preprocesamiento de Grounding DINO (800x800 letterbox)."""
        return ModelInputSpec(
            target_size=(800, 800),
            resize_mode="letterbox",
            mean=(0.485, 0.456, 0.406),
            std=(0.229, 0.224, 0.225),
        )

    def close(self) -> None:
        """Libera el modelo de memoria."""
        self.model = None
        self.processor = None
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
