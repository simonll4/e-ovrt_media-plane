"""Contratos para eventos y resúmenes de corrida."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from pydantic import BaseModel, Field, model_validator
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

    read_ms: float = 0.0
    preprocess_ms: float = 0.0
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

    # Campos de compatibilidad antigua
    source_path: str | None = Field(default=None)
    model_adapter: str | None = Field(default=None)
    prompt_version: str | None = Field(default=None)
    timing_ms: dict[str, float] | None = Field(default=None)

    @model_validator(mode="before")
    @classmethod
    def backport_flat_fields(cls, data: Any) -> Any:
        if isinstance(data, dict):
            # Convertir formato plano (antiguo) a estructurado (nuevo)
            if "source_path" in data and "source" not in data:
                data["source"] = {
                    "source_id": Path(data["source_path"]).name,
                    "source_type": data.get("source_type", "image"),
                    "frame_index": data.get("frame_index"),
                    "timestamp_ms": data.get("timestamp_ms"),
                    "width": data.get("width", 0),
                    "height": data.get("height", 0),
                }
            if "model_adapter" in data and "model" not in data:
                data["model"] = {
                    "name": data["model_adapter"],
                    "model_id": data.get("model_id"),
                    "device": data.get("device", "cpu"),
                }
            if "prompt_version" in data and "prompts" not in data:
                data["prompts"] = {
                    "prompt_set_id": data["prompt_version"],
                }
            if "timing_ms" in data and "timing" not in data:
                t_ms = data["timing_ms"] or {}
                data["timing"] = {
                    "inference_ms": t_ms.get("inference", 0.0),
                    "total_ms": t_ms.get("total", 0.0),
                }

            # Sincronizar campos planos desde los estructurados para consumo de código antiguo
            if "source" in data and not data.get("source_path"):
                src = data["source"]
                if isinstance(src, dict):
                    # Para compatibilidad, si source_id no es un path completo, intentamos reconstruirlo o usarlo directo
                    data["source_path"] = src.get("source_id", "")
            if "model" in data and not data.get("model_adapter"):
                mdl = data["model"]
                if isinstance(mdl, dict):
                    data["model_adapter"] = mdl.get("name", "")
            if "prompts" in data and not data.get("prompt_version"):
                pr = data["prompts"]
                if isinstance(pr, dict):
                    data["prompt_version"] = pr.get("prompt_set_id", "")
            if "timing" in data and not data.get("timing_ms"):
                t = data["timing"]
                if isinstance(t, dict):
                    data["timing_ms"] = {
                        "total": t.get("total_ms", 0.0),
                        "inference": t.get("inference_ms", 0.0),
                    }
        return data


class RunSummary(BaseModel):
    """Resumen de una corrida completa."""

    schema_version: str = "media.summary.v1"
    run_id: str
    scenario: str
    model_adapter: str | None = None
    model_name: str | None = None
    prompt_version: str | None = None
    prompt_set_id: str | None = None
    source_type: str | None = None
    source_count: int
    units_processed: int
    units_failed: int
    total_detections: int = 0
    avg_latency_ms: float = 0.0
    p50_latency_ms: float = 0.0
    p95_latency_ms: float = 0.0
    fps_effective: float = 0.0
    device: str | None = None
    duration_seconds: float = 0.0
    started_at: str
    finished_at: str

    @model_validator(mode="before")
    @classmethod
    def sync_summary_fields(cls, data: Any) -> Any:
        if isinstance(data, dict):
            if "model_adapter" in data and "model_name" not in data:
                data["model_name"] = data["model_adapter"]
            elif "model_name" in data and "model_adapter" not in data:
                data["model_adapter"] = data["model_name"]

            if "prompt_version" in data and "prompt_set_id" not in data:
                data["prompt_set_id"] = data["prompt_version"]
            elif "prompt_set_id" in data and "prompt_version" not in data:
                data["prompt_version"] = data["prompt_set_id"]
        return data
