"""Adaptador mock para testing del pipeline sin GPU ni modelos reales."""

from __future__ import annotations

import random
from pathlib import Path

from PIL import Image

from eovrt_media.contracts.detection import RawDetection
from eovrt_media.models.base import BaseDetectorAdapter, ModelInputSpec


class MockDetectorAdapter(BaseDetectorAdapter):
    """Genera detecciones aleatorias para validar el pipeline completo."""

    def __init__(self, seed: int = 42) -> None:
        self.seed = seed
        self._rng = random.Random(seed)

    def load(self) -> None:
        """No necesita cargar nada."""

    def predict(self, image: Image.Image | Path, prompts: list[str]) -> list[RawDetection]:
        """Genera detecciones aleatorias para cada prompt."""
        # Obtener dimensiones
        if isinstance(image, Path):
            img = Image.open(image)
            width, height = img.size
        else:
            width, height = image.size

        detections = []
        for prompt in prompts:
            # Generar entre 0 y 3 detecciones por prompt
            n_detections = self._rng.randint(0, 3)
            for _ in range(n_detections):
                # Generar bounding box aleatorio válido
                x1 = self._rng.uniform(0, width * 0.7)
                y1 = self._rng.uniform(0, height * 0.7)
                x2 = self._rng.uniform(x1 + 20, min(x1 + width * 0.4, width))
                y2 = self._rng.uniform(y1 + 20, min(y1 + height * 0.4, height))

                detections.append(
                    RawDetection(
                        label=prompt,
                        score=self._rng.uniform(0.3, 0.99),
                        box_xyxy=[x1, y1, x2, y2],
                    )
                )

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
