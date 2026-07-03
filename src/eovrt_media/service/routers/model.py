"""GET /api/model — el modelo fijo de esta instancia (Spec A §3.1)."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

router = APIRouter(prefix="/api")


@router.get("/model")
def get_model(request: Request) -> dict:
    section = getattr(request.app.state, "model_section", None)
    if section is None:
        raise HTTPException(status_code=503, detail="Modelo no cargado")
    return {
        "ref": section.ref,
        "name": section.name,
        "adapter": section.adapter,
        "device": section.device,
        "thresholds": {
            "box": section.box_threshold,
            "text": section.text_threshold,
            "confidence": section.confidence_threshold,
            "iou": section.iou_threshold,
        },
        "runtime": {
            "half_precision": section.runtime.half_precision,
            "warmup": section.runtime.warmup,
        },
    }
