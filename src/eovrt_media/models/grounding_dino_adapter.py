"""Adaptador de Grounding DINO usando Hugging Face Transformers."""

from __future__ import annotations

import logging
import warnings
from contextlib import nullcontext
from pathlib import Path

import numpy as np
from PIL import Image

from eovrt_media.config.prompt_plan import PromptPlan
from eovrt_media.contracts.detection import RawDetection
from eovrt_media.contracts.normalized_unit import NormalizedUnit
from eovrt_media.models.base import BaseDetectorAdapter, ModelInputSpec
from eovrt_media.models.runtime_utils import make_warmup_image, resolve_device, should_use_half
from eovrt_media.preprocessing import prepare_model_input

logger = logging.getLogger(__name__)


def _nms_per_canonical(
    detections: list[RawDetection], iou_threshold: float | None
) -> list[RawDetection]:
    """Aplica NMS greedy **por clase canónica** sobre detecciones ya ligadas.

    Grounding DINO en modo grounding no aplica NMS (solo umbraliza), por lo que emite
    cajas solapadas duplicadas. Agrupamos por ``label`` canónico (no class-agnostic:
    person/helmet/vest se solapan legítimamente) y suprimimos solapamientos dentro de
    cada clase con ``torchvision.ops.batched_nms``. Devuelve los supervivientes en el
    orden original (estable).
    """
    if not detections or iou_threshold is None:
        return detections

    import torch
    from torchvision.ops import batched_nms

    boxes = torch.tensor([d.box_xyxy for d in detections], dtype=torch.float32)
    scores = torch.tensor([d.score for d in detections], dtype=torch.float32)
    group_of: dict[str, int] = {}
    idxs = torch.tensor(
        [group_of.setdefault(d.label, len(group_of)) for d in detections],
        dtype=torch.int64,
    )
    keep = batched_nms(boxes, scores, idxs, float(iou_threshold)).tolist()
    return [detections[i] for i in sorted(keep)]


class GroundingDinoHFAdapter(BaseDetectorAdapter):
    """Adaptador para Grounding DINO via Hugging Face Transformers.

    Usa AutoProcessor + AutoModelForZeroShotObjectDetection.
    """

    PROMPT_BACKEND = "gdino"

    def __init__(
        self,
        model_id: str = "IDEA-Research/grounding-dino-tiny",
        device: str = "cpu",
        box_threshold: float = 0.35,
        text_threshold: float = 0.25,
        iou_threshold: float | None = 0.5,
        local_dir: str | None = None,
        half_precision: bool = False,
        warmup: bool = False,
    ) -> None:
        self.model_id = model_id
        self.device = device
        self.box_threshold = box_threshold
        self.text_threshold = text_threshold
        self.iou_threshold = iou_threshold
        self.local_dir = local_dir
        self.half_precision = half_precision
        self.warmup = warmup
        self.processor = None
        self.model = None

    def load(self) -> None:
        """Carga el processor y modelo en el dispositivo configurado."""
        from transformers import AutoModelForZeroShotObjectDetection, AutoProcessor

        self.device = resolve_device(self.device)
        source = self.local_dir if self.local_dir and Path(self.local_dir).exists() else self.model_id
        logger.info(f"Cargando Grounding DINO desde: {source} → {self.device}")

        self.processor = AutoProcessor.from_pretrained(source)
        self.model = AutoModelForZeroShotObjectDetection.from_pretrained(source).to(self.device)
        self.model.eval()

        if self.warmup:
            dummy = Image.fromarray(make_warmup_image(self.input_spec.target_size))
            self.predict(dummy, PromptPlan.from_texts(["object"], "gdino"))

        logger.info("Grounding DINO cargado correctamente.")

    def predict(self, image: Image.Image | Path, plan: PromptPlan) -> list[RawDetection]:
        """Ejecuta inferencia con Grounding DINO.

        Args:
            image: Imagen PIL o ruta a archivo.
            plan: PromptPlan resuelto; el caption se arma con ``plan.texts()``.

        Returns:
            Lista de RawDetection ligadas al plan, con boxes en píxeles.
        """
        if self.model is None or self.processor is None:
            raise RuntimeError("Modelo no cargado. Llamar load() primero.")

        # Aceptar Path, PIL o numpy RGB (evita copia PIL en el hot path)
        if isinstance(image, Path):
            image = Image.open(image).convert("RGB")
        elif not isinstance(image, (Image.Image, np.ndarray)):
            raise TypeError(f"Tipo de imagen no soportado: {type(image)}")

        # Construir caption para Grounding DINO: "prompt1. prompt2. prompt3."
        text = ". ".join(plan.texts()) + "."

        inputs = self.processor(images=image, text=text, return_tensors="pt").to(self.device)

        return self._run_inference(
            inputs,
            plan,
            target_size=(
                image.shape[:2]
                if isinstance(image, np.ndarray)
                else (image.size[1], image.size[0])
            ),
        )

    def _run_inference(
        self,
        inputs,
        plan: PromptPlan,
        target_size: tuple[int, int],
    ) -> list[RawDetection]:
        """Ejecuta y decodifica una entrada ya preparada para Grounding DINO."""
        import torch

        amp = (
            torch.autocast("cuda", dtype=torch.float16)
            if should_use_half(self.device, self.half_precision)
            else nullcontext()
        )
        with torch.no_grad(), amp:
            outputs = self.model(**inputs)

        with warnings.catch_warnings():
            # simplefilter por categoría (no por módulo): el FutureWarning de
            # post_process ('labels' deprecated → usamos text_labels) se atribuye
            # de forma inconsistente al módulo, así que el filtro con module= no lo
            # atrapaba y spameaba el log. La categoría sí lo suprime de forma fiable.
            warnings.simplefilter("ignore", FutureWarning)
            results = self.processor.post_process_grounded_object_detection(
                outputs,
                inputs.input_ids,
                threshold=self.box_threshold,
                text_threshold=self.text_threshold,
                target_sizes=[list(target_size)],  # [height, width]
            )[0]

        detections = []
        boxes = results["boxes"].cpu().tolist()
        scores = results["scores"].cpu().tolist()
        # 'text_labels' es la clave estable. Acceder a 'labels' (deprecada) dispara
        # un FutureWarning por frame, y como es el default de .get() Python lo evalúa
        # SIEMPRE de forma eager (incluso con text_labels presente) → spam de logs.
        # Solo se consulta 'labels' como fallback real cuando falta text_labels.
        if "text_labels" in results:
            raw_labels = results["text_labels"]
        else:
            raw_labels = results.get("labels", [])
        if hasattr(raw_labels, "tolist"):
            raw_labels = raw_labels.tolist()

        by_text = plan.by_text()
        texts = plan.texts()
        for box, score, label in zip(boxes, scores, raw_labels):
            det = self._bind_span(
                str(label).strip(), float(score), [float(c) for c in box], by_text, texts
            )
            if det is not None:
                detections.append(det)

        return _nms_per_canonical(detections, self.iou_threshold)

    def _bind_span(self, detected, score, box, by_text, texts):
        """Resuelve un span de GDINO contra el plan; None si no matchea (se descarta)."""
        phrase = by_text.get(detected)
        if phrase is None:
            dl = detected.lower()
            match = (
                next((t for t in texts if t.lower() == dl), None)
                or next((t for t in texts if dl in t.lower()), None)
                or next((t for t in texts if t.lower() in dl), None)
            )
            if match is None and texts:
                dw = set(dl.split())
                best = max(texts, key=lambda t: len(dw & set(t.lower().split())))
                if dw & set(best.lower().split()):
                    match = best
            phrase = by_text.get(match) if match else None
        if phrase is None:
            logger.warning("GDINO span '%s' no resuelto contra el plan; descartado.", detected)
            return None
        return RawDetection(
            label=phrase.canonical,
            prompt_id=phrase.prompt_id,
            source_prompt=phrase.text,
            strategy=phrase.strategy,
            condition_id=phrase.condition_id,
            score=score,
            box_xyxy=box,
        )

    def forward(self, unit: NormalizedUnit, plan: PromptPlan) -> list[RawDetection]:
        """Ejecuta la inferencia desde el payload normalizado del canal."""
        if self.model is None or self.processor is None:
            raise RuntimeError("Modelo no cargado. Llamar load() primero.")

        text = ". ".join(plan.texts()) + "."
        inputs = self.processor(text=text, return_tensors="pt").to(self.device)
        inputs["pixel_values"] = prepare_model_input(unit, self.input_spec, self.device)
        return self._run_inference(inputs, plan, unit.payload.shape[:2])

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
        import torch

        self.model = None
        self.processor = None
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
