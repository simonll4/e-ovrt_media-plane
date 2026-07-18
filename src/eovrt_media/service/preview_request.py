"""Contrato HTTP de la sesión de preview (POST /api/preview)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from eovrt_media.service.run_request import IngestSpec, PromptsSpec, RunRequest

# Set dummy para modo raw: permite reutilizar el loader de runs (que exige prompts)
# sin ejecutar inferencia alguna.
_RAW_DUMMY_SET = {"id": "preview_raw", "classes": [{"id": "x", "phrasings": {"default": ["x"]}}]}


class PreviewParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    score_threshold: float | None = Field(default=None, ge=0.0, le=1.0)


class PreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Literal["raw", "detect"]
    ingest: IngestSpec
    prompts: PromptsSpec | None = None
    params: PreviewParams = Field(default_factory=PreviewParams)

    @model_validator(mode="after")
    def _detect_requiere_prompts(self) -> "PreviewRequest":
        if self.mode == "detect" and self.prompts is None:
            raise ValueError("mode=detect requiere 'prompts'")
        return self


def to_run_request(req: PreviewRequest) -> RunRequest:
    prompts = req.prompts or PromptsSpec(set_inline=_RAW_DUMMY_SET)
    return RunRequest(ingest=req.ingest, prompts=prompts)
