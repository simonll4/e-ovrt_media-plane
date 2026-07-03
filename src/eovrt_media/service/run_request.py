"""Contrato canónico del run request (Spec A §3.1) y su traducción a run config."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from eovrt_media.config.schemas import ModelSection

_PLUGIN_TO_SOURCE_TYPE = {
    "image_folder": "image_folder",
    "video_file": "video_file",
    "rtsp": "rtsp",
    "oak_d": "oak_d",
}


class IngestSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    plugin: str
    config: dict[str, Any] = Field(default_factory=dict)


class PromptsSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    set_inline: dict[str, Any]
    active_ids: list[str] | None = None


class RunParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    stride: int | None = None
    max_units: int | None = None
    save_annotated_video: bool = False
    save_previews: bool = True
    name: str | None = None


class RunRequest(BaseModel):
    # extra="forbid": una sección 'model' (u otra desconocida) en el body → 422.
    model_config = ConfigDict(extra="forbid")
    ingest: IngestSpec
    prompts: PromptsSpec
    run: RunParams = Field(default_factory=RunParams)


def to_raw_run_config(request: RunRequest, model_section: ModelSection) -> dict[str, Any]:
    """Traduce el request canónico al dict de run config del loader.

    El modelo NUNCA viene del request: es el que la instancia cargó al startup.
    """
    if request.ingest.plugin not in _PLUGIN_TO_SOURCE_TYPE:
        raise ValueError(
            f"Plugin de ingesta desconocido: {request.ingest.plugin!r}. "
            f"Disponibles: {sorted(_PLUGIN_TO_SOURCE_TYPE)}"
        )
    ingest_config = dict(request.ingest.config)
    dataset = ingest_config.pop("dataset", None)
    if dataset:
        source: dict[str, Any] = {"ref": dataset, **ingest_config}
    else:
        source = {"type": _PLUGIN_TO_SOURCE_TYPE[request.ingest.plugin], **ingest_config}

    raw: dict[str, Any] = {
        "run": {"name": request.run.name, "max_units": request.run.max_units},
        "source": source,
        "model": model_section.model_dump(exclude_none=True),
        "prompts": {
            "set_inline": request.prompts.set_inline,
            "active_ids": request.prompts.active_ids,
        },
        "outputs": {
            "save_annotated_video": request.run.save_annotated_video,
            "save_previews": request.run.save_previews,
        },
    }
    if request.run.stride is not None:
        raw["rate_control"] = {"stride": request.run.stride}
    return raw
