"""Contratos para eventos y resúmenes de corrida."""

from __future__ import annotations

from pydantic import BaseModel, Field
from eovrt_media.contracts.detection import Detection


class DetectionEventSource(BaseModel):
    """Información de la fuente de la unidad visual."""

    source_id: str
    source_type: str
    frame_index: int | None = None
    timestamp_ms: float | None = None
    width: int
    height: int


class DetectionEventModel(BaseModel):
    """Información del modelo usado en el evento."""

    name: str
    model_id: str | None = None
    device: str


class DetectionEventPrompts(BaseModel):
    """Información de los prompts usados."""

    prompt_set_id: str


class DetectionEventTiming(BaseModel):
    """Desglose de tiempos medidos en milisegundos."""

    normalize_ms: float = 0.0
    inference_ms: float = 0.0
    postprocess_ms: float = 0.0
    write_ms: float = 0.0
    total_ms: float = 0.0


class DetectionEvent(BaseModel):
    """Evento principal del plano de medios — agrupa detecciones de una unidad visual."""

    schema_version: str = "media.detection.v1"
    event_type: str = "detection_event"
    run_id: str
    unit_id: str
    source: DetectionEventSource
    model: DetectionEventModel
    prompts: DetectionEventPrompts
    detections: list[Detection]
    timing: DetectionEventTiming


class RunDescriptor(BaseModel):
    """Claves de comparación del despliegue persistidas en ``summary.json``."""

    scenario: str
    topology: str
    transport: dict
    rate_control: dict
    source_kind: str
    model: str
    prompt_set: str | None = None
    device: str | None = None
    code_version: str | None = None


class RunSummary(BaseModel):
    """Resumen de una corrida completa."""

    schema_version: str = "media.summary.v2"
    run_id: str
    scenario: str
    model_name: str | None = None
    prompt_set_id: str | None = None
    source_type: str | None = None
    source_count: int
    units_processed: int
    units_failed: int
    total_detections: int = 0
    detections_by_label: dict[str, int] = Field(default_factory=dict)
    detections_by_prompt_id: dict[str, int] = Field(default_factory=dict)
    avg_latency_ms: float = 0.0
    p50_latency_ms: float = 0.0
    p95_latency_ms: float = 0.0
    p99_latency_ms: float = 0.0
    fps_effective: float = 0.0
    gpu_memory_peak_mb: float = 0.0
    device: str | None = None
    duration_seconds: float = 0.0
    started_at: str
    finished_at: str
    units_dropped: int = 0
    backpressure_wait_ms: float = 0.0
    max_staleness_observed_ms: float = 0.0
    run_descriptor: RunDescriptor | None = None
