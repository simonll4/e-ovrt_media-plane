"""Adaptador mock para testing del pipeline sin GPU ni modelos reales."""

from __future__ import annotations

import random
from pathlib import Path
from typing import TYPE_CHECKING

from PIL import Image

from eovrt_media.contracts.detection import RawDetection
from eovrt_media.contracts.normalized_unit import NormalizedUnit
from eovrt_media.models.base import BaseDetectorAdapter, ModelInputSpec

if TYPE_CHECKING:
    from eovrt_media.config.prompt_plan import PromptPhrase, PromptPlan


class MockDetectorAdapter(BaseDetectorAdapter):
    """Genera detecciones aleatorias para validar el pipeline completo."""

    def __init__(self, seed: int = 42) -> None:
        self.seed = seed
        self._rng = random.Random(seed)

    def load(self) -> None:
        """No necesita cargar nada."""

    def _bind(self, phrase: PromptPhrase, box: list[float]) -> RawDetection:
        """Construye una RawDetection ligada a la frase del plan."""
        return RawDetection(
            label=phrase.canonical,
            prompt_id=phrase.prompt_id,
            source_prompt=phrase.text,
            strategy=phrase.strategy,
            condition_id=phrase.condition_id,
            score=self._rng.uniform(0.3, 0.99),
            box_xyxy=box,
        )

    def predict(self, image: Image.Image | Path, plan: PromptPlan) -> list[RawDetection]:
        """Genera detecciones aleatorias para cada frase del plan."""
        if isinstance(image, Path):
            width, height = Image.open(image).size
        else:
            width, height = image.size

        detections = []
        for phrase in plan.by_index():
            for _ in range(self._rng.randint(0, 3)):
                x1 = self._rng.uniform(0, width * 0.7)
                y1 = self._rng.uniform(0, height * 0.7)
                x2 = self._rng.uniform(x1 + 20, min(x1 + width * 0.4, width))
                y2 = self._rng.uniform(y1 + 20, min(y1 + height * 0.4, height))
                detections.append(self._bind(phrase, [x1, y1, x2, y2]))
        return detections

    def forward(self, unit: NormalizedUnit, plan: PromptPlan) -> list[RawDetection]:
        """Genera detecciones en el espacio ``target_size`` normalizado."""
        target_h, target_w = unit.target_size
        detections = []
        for phrase in plan.by_index():
            for _ in range(self._rng.randint(0, 3)):
                x1 = self._rng.uniform(0, target_w * 0.7)
                y1 = self._rng.uniform(0, target_h * 0.7)
                x2 = self._rng.uniform(x1 + 20, min(x1 + target_w * 0.4, target_w))
                y2 = self._rng.uniform(y1 + 20, min(y1 + target_h * 0.4, target_h))
                detections.append(self._bind(phrase, [x1, y1, x2, y2]))
        return detections

    @property
    def input_spec(self) -> ModelInputSpec:
        """Especificación de preprocesamiento del mock (640x640 letterbox)."""
        return ModelInputSpec(
            target_size=(640, 640),
            resize_mode="letterbox",
            mean=(0.0, 0.0, 0.0),
            std=(1.0, 1.0, 1.0),
        )

    def close(self) -> None:
        """Nada que liberar."""
