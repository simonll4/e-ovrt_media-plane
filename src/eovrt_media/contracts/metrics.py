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
    # Insumos de t_capture->alert (spec 40 SS5.2.4). El join con el plano de
    # control es por `unit_id`. Aditivos: default 0 para artefactos viejos.
    capture_monotonic_ns: int = 0
    capture_wallclock_ms: float = 0.0
    # Compuesta captura -> resultado algoritmico (cierra al terminar la inferencia).
    # None = no medible (p.ej. topologia two_node: relojes monotonicos de hosts
    # distintos no son comparables). Distinto de 0.0, que seria un valor legitimo.
    g2a_ms: float | None = None
    # Tramo sensor->host (solo oak_d; None = fuente sin timestamps de device).
    capture_to_host_ms: float | None = None
    fps_effective: float = 0.0
    latency_total_ms: float = 0.0
    latency_inference_ms: float = 0.0
    latency_normalize_ms: float = 0.0
    detections_count: int = 0
    dropped_units: int = 0
    device: str = "cpu"
    gpu_memory_allocated_mb: float = 0.0
