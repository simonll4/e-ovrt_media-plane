"""Esquemas de configuración del plano de medios E-OVRT."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, model_validator


# ---------------------------------------------------------------------------
# Prompt config
# ---------------------------------------------------------------------------


class PromptItem(BaseModel):
    """Un prompt individual con su ID, texto, aliases, rol y habilitación por defecto."""

    id: str
    text: str
    aliases: list[str] = Field(default_factory=list)
    role: str | None = None
    enabled_by_default: bool = Field(default=True)


class PromptSet(BaseModel):
    """Conjunto de prompts estructurado según MEMORIA."""

    id: str
    description: str | None = None
    language: str | None = None
    items: list[PromptItem]


class PromptsFile(BaseModel):
    """Archivo completo de prompts que soporta formato antiguo y nuevo (MEMORIA)."""

    version: str | None = None
    items: list[PromptItem] | None = None
    prompt_set: PromptSet | None = None

    @model_validator(mode="after")
    def validate_formats(self) -> PromptsFile:
        if self.prompt_set is None and (self.version is None or self.items is None):
            raise ValueError("Debe proveer 'prompt_set' o bien 'version' e 'items'")
        if self.prompt_set:
            self.version = self.prompt_set.id
            self.items = self.prompt_set.items
        return self

    @property
    def active_items_all(self) -> list[PromptItem]:
        if self.prompt_set:
            return self.prompt_set.items
        return self.items or []

    @property
    def resolved_version(self) -> str:
        if self.prompt_set:
            return self.prompt_set.id
        return self.version or "unknown"

    def get_active_texts(self, active_ids: list[str] | None) -> list[str]:
        """Devuelve los textos de los prompts activos, en orden."""
        return [item.text for item in self.get_active_items(active_ids)]

    def get_active_items(self, active_ids: list[str] | None) -> list[PromptItem]:
        """Devuelve los PromptItem activos, en orden o filtrados."""
        all_items = self.active_items_all
        id_to_item = {item.id: item for item in all_items}
        
        if active_ids is None:
            # Por defecto, solo los habilitados
            return [item for item in all_items if item.enabled_by_default]
            
        result = []
        for pid in active_ids:
            if pid not in id_to_item:
                raise ValueError(f"Prompt ID '{pid}' no encontrado en archivo de prompts.")
            result.append(id_to_item[pid])
        return result


# ---------------------------------------------------------------------------
# Run config sections
# ---------------------------------------------------------------------------


class RunSection(BaseModel):
    """Sección 'run' de la configuración."""

    id: str | None = None
    scenario: str = "DBE"
    name: str | None = None
    description: str | None = None
    seed: int = 42
    max_units: int | None = None


class SourceSection(BaseModel):
    """Sección 'source' de la configuración.

    Puede definirse inline (type + path) o por referencia al catálogo de
    datasets: ``ref: <nombre>`` resuelve ``configs/datasets/<nombre>.yaml``.
    """

    ref: str | None = None
    description: str | None = None

    type: str = "image_folder"
    path: str
    extensions: list[str] = Field(default_factory=lambda: [".jpg", ".jpeg", ".png"])
    kind: str | None = None
    dataset_id: str | None = None
    view: str | None = None
    split: str | None = None
    vocabulary: list[str] | None = None

    # Fuente viva (RTSP / cámaras IP)
    url: str | None = None
    reconnect_retries: int = 5
    reconnect_delay_ms: int = 1000


class SamplingConfig(BaseModel):
    """Sección 'sampling' de la configuración."""

    mode: str = "all"
    every_n: int = 1
    target_fps: float | None = None
    max_units: int | None = None


class RateControlConfig(BaseModel):
    """Sección ``rate_control``: política de control de tasa del productor."""

    policy: str = "deterministic"
    stride: int = 1
    max_queue_size: int = 8
    overflow: str = "fail_run"
    buffer_size: int = 2
    max_staleness_ms: float | None = None


class TransportConfig(BaseModel):
    """Sección ``transport``: backend del canal productor-consumidor."""

    backend: str = "memory"
    payload_format: str = "uint8_rgb"
    endpoint: str | None = None


class TopologyConfig(BaseModel):
    """Sección ``topology``: disposición de nodos del despliegue."""

    mode: str = "single_host"


class ModelSection(BaseModel):
    """Sección 'model' de la configuración.

    Puede definirse inline o por referencia al catálogo de modelos:
    ``ref: <familia>/<variante>`` resuelve ``configs/models/<familia>/<variante>.yaml``.
    Los campos declarados en la run config pisan los del catálogo.
    """

    ref: str | None = None
    family: str | None = None
    variant: str | None = None
    lineage: str | None = None  # original | finetuned
    description: str | None = None
    source: str | None = None  # URL de descarga del checkpoint
    license: str | None = None

    name: str | None = None
    adapter: str | None = None
    device: str = "cpu"

    # Grounding DINO fields
    model_id: str | None = None
    local_dir: str | None = None
    box_threshold: float = 0.35
    text_threshold: float = 0.25

    # YOLOE fields
    weights: str | None = None
    confidence_threshold: float = 0.25
    iou_threshold: float = 0.50
    image_size: int | list[int] | None = None

    @model_validator(mode="before")
    @classmethod
    def sync_name_and_adapter(cls, data: Any) -> Any:
        if isinstance(data, dict):
            if "name" in data and "adapter" not in data:
                data["adapter"] = data["name"]
            elif "adapter" in data and "name" not in data:
                data["name"] = data["adapter"]
        return data


class PromptsSection(BaseModel):
    """Sección 'prompts' de la configuración.

    Acepta ``ref: <nombre>`` (resuelve ``configs/prompts/<nombre>.yaml``)
    o una ruta explícita en ``file``.
    """

    ref: str | None = None
    file: str | None = None
    active_ids: list[str] | None = None

    @model_validator(mode="after")
    def require_ref_or_file(self) -> PromptsSection:
        if self.ref is None and self.file is None:
            raise ValueError("La sección 'prompts' requiere 'ref' o 'file'")
        return self


class PostprocessConfig(BaseModel):
    """Sección 'postprocess' de la configuración."""

    min_confidence: float = 0.25
    min_box_area_px: float = 100.0
    normalize_boxes: bool = True


class OutputsConfig(BaseModel):
    """Sección 'outputs' (o 'output') de la configuración."""

    run_dir: str = "runs"
    base_dir: str = "runs"
    save_detections_jsonl: bool = True
    save_metrics_jsonl: bool = True
    save_errors_jsonl: bool = True
    save_previews: bool = True
    preview_max: int = 20

    # Campos de compatibilidad antigua
    save_jsonl: bool | None = None
    save_summary: bool | None = None

    @model_validator(mode="before")
    @classmethod
    def sync_outputs(cls, data: Any) -> Any:
        if isinstance(data, dict):
            if "run_dir" in data and "base_dir" not in data:
                data["base_dir"] = data["run_dir"]
            elif "base_dir" in data and "run_dir" not in data:
                data["run_dir"] = data["base_dir"]
            
            # Sync con campos antiguos
            if "save_jsonl" in data:
                val = data["save_jsonl"]
                data["save_detections_jsonl"] = data.get("save_detections_jsonl", val)
                data["save_metrics_jsonl"] = data.get("save_metrics_jsonl", val)
                data["save_errors_jsonl"] = data.get("save_errors_jsonl", val)
        return data


class LoggingConfig(BaseModel):
    """Sección 'logging' de la configuración."""

    level: str = "INFO"


# ---------------------------------------------------------------------------
# Top-level config
# ---------------------------------------------------------------------------


class RunConfig(BaseModel):
    """Configuración completa de una corrida."""

    run: RunSection
    source: SourceSection
    model: ModelSection
    prompts: PromptsSection
    
    rate_control: RateControlConfig = Field(default_factory=RateControlConfig)
    transport: TransportConfig = Field(default_factory=TransportConfig)
    topology: TopologyConfig = Field(default_factory=TopologyConfig)
    postprocess: PostprocessConfig = Field(default_factory=PostprocessConfig)
    outputs: OutputsConfig = Field(default_factory=OutputsConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)

    # Resolved at load time
    prompts_file: PromptsFile | None = Field(default=None, exclude=True)
    config_path: Path | None = Field(default=None, exclude=True)

    @model_validator(mode="before")
    @classmethod
    def handle_outputs_and_defaults(cls, data: Any) -> Any:
        if isinstance(data, dict):
            # Mapear output -> outputs
            if "output" in data and "outputs" not in data:
                data["outputs"] = data["output"]
            elif "outputs" in data and "output" not in data:
                data["output"] = data["outputs"]
                
            # Inicializar secciones si faltan
            for field in (
                "rate_control",
                "transport",
                "topology",
                "postprocess",
                "outputs",
                "logging",
            ):
                if field not in data:
                    data[field] = {}
        return data

    @property
    def output(self) -> OutputsConfig:
        """Propiedad de compatibilidad para código anterior."""
        return self.outputs

    @property
    def sampling(self) -> SamplingConfig:
        """Vista transitoria para el pipeline previo al refactor de Task 6.

        Los YAML ya no pueden declarar ``sampling``; la configuración efectiva solo
        serializa ``rate_control`` y ``run.max_units``.
        """
        return SamplingConfig(
            mode="every_n" if self.rate_control.stride > 1 else "all",
            every_n=self.rate_control.stride,
            max_units=self.run.max_units,
        )

    def get_prompt_texts(self) -> list[str]:
        """Devuelve los textos de los prompts activos."""
        if self.prompts_file is None:
            raise RuntimeError("Archivo de prompts no cargado. Usar load_run_config().")
        return self.prompts_file.get_active_texts(self.prompts.active_ids)

    def get_prompt_items(self) -> list[PromptItem]:
        """Devuelve los PromptItem activos."""
        if self.prompts_file is None:
            raise RuntimeError("Archivo de prompts no cargado. Usar load_run_config().")
        return self.prompts_file.get_active_items(self.prompts.active_ids)

    def to_effective_dict(self) -> dict[str, Any]:
        """Devuelve la configuración efectiva como diccionario serializable."""
        data = self.model_dump(exclude={"prompts_file", "config_path"})
        if self.prompts_file:
            data["resolved_prompts"] = self.get_prompt_texts()
        return data
