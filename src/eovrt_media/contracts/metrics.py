"""Contratos para las métricas de rendimiento."""

from __future__ import annotations

from typing import Any
from pydantic import BaseModel, model_validator


class MetricSample(BaseModel):
    """Métrica individual por unidad visual procesada."""

    schema_version: str = "media.metric.v2"
    event_type: str = "metric_sample"
    run_id: str
    unit_id: str
    source_path: str | None = None
    fps_effective: float = 0.0
    latency_total_ms: float = 0.0
    latency_inference_ms: float = 0.0
    latency_normalize_ms: float = 0.0
    detections_count: int = 0
    dropped_units: int = 0
    device: str = "cpu"
    gpu_memory_allocated_mb: float = 0.0

    # Campos de compatibilidad antigua
    inference_ms: float | None = None
    total_ms: float | None = None
    detection_count: int | None = None
    error: str | None = None

    @model_validator(mode="before")
    @classmethod
    def sync_metrics_fields(cls, data: Any) -> Any:
        if isinstance(data, dict):
            # Formato viejo -> nuevo
            if "inference_ms" in data and "latency_inference_ms" not in data:
                data["latency_inference_ms"] = data["inference_ms"]
            if "total_ms" in data and "latency_total_ms" not in data:
                data["latency_total_ms"] = data["total_ms"]
            if "detection_count" in data and "detections_count" not in data:
                data["detections_count"] = data["detection_count"]

            # Formato nuevo -> viejo
            if "latency_inference_ms" in data and "inference_ms" not in data:
                data["inference_ms"] = data["latency_inference_ms"]
            if "latency_total_ms" in data and "total_ms" not in data:
                data["total_ms"] = data["latency_total_ms"]
            if "detections_count" in data and "detection_count" not in data:
                data["detection_count"] = data["detections_count"]
        return data
