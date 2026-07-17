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


class G2ASummary(BaseModel):
    """Compuesta captura -> resultado algoritmico, con su estado de aplicabilidad."""

    state: str  # computed | applicable_not_computed | not_applicable | not_interpretable
    causes: list[str] = Field(default_factory=list)
    count: int = 0
    warmup_units: int = 0
    avg_ms: float = 0.0
    p50_ms: float = 0.0
    p95_ms: float = 0.0
    p99_ms: float = 0.0
    budget_min_ms: float = 50.0
    budget_max_ms: float = 250.0
    p95_within_budget: bool = False


class RunSummary(BaseModel):
    """Resumen de una corrida completa."""

    schema_version: str = "media.summary.v2"
    run_id: str
    scenario: str
    model_name: str | None = None
    prompt_set_id: str | None = None
    experiment_id: str | None = None
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
    # Que reloj emite la fuente: decide la aplicabilidad de t_capture->alert
    # aguas abajo (spec 40 SS5.2.3). None = corridas previas a esta task.
    source_clock: str | None = None
    g2a: G2ASummary | None = None
    # p50/p95 del tramo sensor->host (solo corridas oak_d). None = sin muestras.
    capture_to_host: dict | None = None
    # Bloque EN-2 (spec 2026-07-15 §6): siempre presente; {"enabled": false}
    # cuando la corrida no usa el prefilter.
    prefilter: dict = Field(default_factory=lambda: {"enabled": False})
