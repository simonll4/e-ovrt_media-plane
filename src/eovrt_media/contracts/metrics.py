"""Contratos para las métricas de rendimiento."""

from __future__ import annotations

from pydantic import BaseModel


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
