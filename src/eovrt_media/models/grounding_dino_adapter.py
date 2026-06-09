"""Adaptador de Grounding DINO usando Hugging Face Transformers."""

from __future__ import annotations

import logging
from pathlib import Path

import torch
from PIL import Image
from transformers import AutoModelForZeroShotObjectDetection, AutoProcessor

from eovrt_media.contracts.detection import RawDetection
from eovrt_media.models.base import BaseDetectorAdapter

logger = logging.getLogger(__name__)


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
        labels = results.get("labels", results.get("text", []))

        # labels puede ser lista de strings o necesitar procesamiento
        if hasattr(labels, "tolist"):
            labels = labels.tolist()

        for box, score, label in zip(boxes, scores, labels):
            detections.append(
                RawDetection(
                    label=str(label).strip(),
                    score=float(score),
                    box_xyxy=[float(c) for c in box],
                )
            )

        return detections

    def close(self) -> None:
        """Libera el modelo de memoria."""
        self.model = None
        self.processor = None
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
