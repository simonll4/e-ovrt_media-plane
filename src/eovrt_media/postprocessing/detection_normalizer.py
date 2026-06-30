"""Normalizador y postprocesador de detecciones."""

from __future__ import annotations

from typing import TYPE_CHECKING

from eovrt_media.contracts import Detection, RawDetection

if TYPE_CHECKING:
    from eovrt_media.contracts.normalized_unit import ResizeTransform


class DetectionNormalizer:
    """Clase encargada de normalizar y filtrar detecciones crudas.

    Aplica filtros de confianza y área y calcula coordenadas normalizadas.
    El binding a la clase canónica (``label``/``prompt_id``) lo hace el
    adaptador por construcción; aquí solo se confía en él.
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
        transform: ResizeTransform | None = None,
    ) -> list[Detection]:
        """Normaliza una lista de detecciones crudas (RawDetection).

        Filtra las detecciones con confianza baja o área pequeña.

        Args:
            raw_detections: Lista de detecciones crudas del adaptador (ya ligadas).
            width: Ancho de la unidad visual en píxeles (espacio original).
            height: Alto de la unidad visual en píxeles (espacio original).
            model_name: Nombre del modelo/adaptador.
            transform: Si se proporciona, reproyecta las cajas del espacio-modelo
                al espacio original antes de calcular coordenadas normalizadas.

        Returns:
            Lista de detecciones normalizadas (Detection).
        """
        normalized_detections = []

        for idx, raw in enumerate(raw_detections):
            # 1. Filtro de confianza
            if raw.score < self.min_confidence:
                continue

            # 2. Reproyectar caja al espacio original si se provee transform
            if transform is not None:
                box_xyxy = transform.project_to_original(raw.box_xyxy)
            else:
                box_xyxy = list(raw.box_xyxy)

            x1, y1, x2, y2 = box_xyxy
            area = (x2 - x1) * (y2 - y1)

            # 3. Filtro de área de bounding box
            if area < self.min_box_area_px:
                continue

            # 4. Calcular caja normalizada
            if self.normalize_boxes and width > 0 and height > 0:
                bbox_norm = [
                    round(max(0.0, min(1.0, x1 / width)), 4),
                    round(max(0.0, min(1.0, y1 / height)), 4),
                    round(max(0.0, min(1.0, x2 / width)), 4),
                    round(max(0.0, min(1.0, y2 / height)), 4),
                ]
            else:
                bbox_norm = [0.0, 0.0, 0.0, 0.0]

            # Generar ID único para la detección en este frame
            det_id = f"det_{idx + 1:06d}"

            normalized_detections.append(
                Detection(
                    detection_id=det_id,
                    label=raw.label,
                    prompt_id=raw.prompt_id,
                    source_prompt=raw.source_prompt,
                    strategy=raw.strategy,
                    condition_id=raw.condition_id,
                    confidence=round(raw.score, 4),
                    bbox_xyxy=[round(c, 1) for c in box_xyxy],
                    bbox_norm_xyxy=bbox_norm,
                    area_px=round(area, 1),
                    model_name=model_name,
                )
            )

        return normalized_detections
