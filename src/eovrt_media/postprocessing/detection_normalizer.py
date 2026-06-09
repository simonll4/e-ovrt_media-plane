"""Normalizador y postprocesador de detecciones."""

from __future__ import annotations

from eovrt_media.contracts import Detection, RawDetection
from eovrt_media.config import PromptItem


class DetectionNormalizer:
    """Clase encargada de normalizar y filtrar detecciones crudas.

    Aplica filtros de confianza y área, calcula coordenadas normalizadas
    y mapea las etiquetas del modelo a los identificadores de prompts.
    """

    def __init__(
        self,
        min_confidence: float = 0.25,
        min_box_area_px: float = 100.0,
        normalize_boxes: bool = True,
    ) -> None:
        self.min_confidence = min_confidence
        self.min_box_area_px = min_box_area_px
        self.normalize_boxes = normalize_boxes

    def normalize(
        self,
        raw_detections: list[RawDetection],
        width: int,
        height: int,
        model_name: str,
        prompt_items: list[PromptItem] | None = None,
    ) -> list[Detection]:
        """Normaliza una lista de detecciones crudas (RawDetection).

        Filtra las detecciones con confianza baja o área pequeña.

        Args:
            raw_detections: Lista de detecciones crudas del adaptador.
            width: Ancho de la unidad visual en píxeles.
            height: Alto de la unidad visual en píxeles.
            model_name: Nombre del modelo/adaptador.
            prompt_items: Lista de PromptItem para resolver prompt_id.

        Returns:
            Lista de detecciones normalizadas (Detection).
        """
        normalized_detections = []
        
        for idx, raw in enumerate(raw_detections):
            # 1. Filtro de confianza
            if raw.score < self.min_confidence:
                continue

            x1, y1, x2, y2 = raw.box_xyxy
            area = (x2 - x1) * (y2 - y1)

            # 2. Filtro de área de bounding box
            if area < self.min_box_area_px:
                continue

            # 3. Calcular caja normalizada
            if self.normalize_boxes and width > 0 and height > 0:
                bbox_norm = [
                    round(max(0.0, min(1.0, x1 / width)), 4),
                    round(max(0.0, min(1.0, y1 / height)), 4),
                    round(max(0.0, min(1.0, x2 / width)), 4),
                    round(max(0.0, min(1.0, y2 / height)), 4),
                ]
            else:
                bbox_norm = [0.0, 0.0, 0.0, 0.0]

            # 4. Mapear etiqueta a prompt_id
            prompt_id = raw.prompt_id
            label_lower = raw.label.lower().strip()
            
            if not prompt_id and prompt_items:
                for item in prompt_items:
                    candidates = [item.text.lower()] + [alias.lower() for alias in item.aliases]
                    if label_lower in candidates:
                        prompt_id = item.id
                        break

            # Generar ID único para la detección en este frame
            det_id = f"det_{idx + 1:06d}"

            normalized_detections.append(
                Detection(
                    detection_id=det_id,
                    label=raw.label,
                    prompt_id=prompt_id,
                    confidence=round(raw.score, 4),
                    bbox_xyxy=[round(c, 1) for c in raw.box_xyxy],
                    bbox_norm_xyxy=bbox_norm,
                    area_px=round(area, 1),
                    model_name=model_name,
                )
            )

        return normalized_detections
