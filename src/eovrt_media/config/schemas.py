"""Esquemas de configuración del plano de medios E-OVRT."""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field, model_validator

if TYPE_CHECKING:
    from eovrt_media.config.prompt_plan import PromptPlan


# ---------------------------------------------------------------------------
# Prompt config
# ---------------------------------------------------------------------------


class PromptClass(BaseModel):
    """Una clase de prompt: identidad estable + fraseo por backend."""

    id: str
    canonical: str | None = None
    role: str | None = None
    strategy: str | None = None
    condition_id: str | None = None
    enabled_by_default: bool = True
    phrasings: dict[str, list[str]]

    @model_validator(mode="after")
    def default_canonical(self) -> PromptClass:
        if self.canonical is None:
            self.canonical = self.id
        return self


class PromptSet(BaseModel):
    """Conjunto canónico de clases de prompt."""

    id: str
    description: str | None = None
    language: str | None = None
    classes: list[PromptClass]


class PromptsFile(BaseModel):
    """Archivo de prompts — formato único (sin legacy)."""

    prompt_set: PromptSet

    def resolved_set_id(self) -> str:
        return self.prompt_set.id

    def get_active_classes(self, active_ids: list[str] | None) -> list[PromptClass]:
        """Devuelve las PromptClass activas, en orden o filtradas."""
        all_classes = self.prompt_set.classes
        if active_ids is None:
            return [c for c in all_classes if c.enabled_by_default]
        by_id = {c.id: c for c in all_classes}
        result = []
        for pid in active_ids:
            if pid not in by_id:
                raise ValueError(f"Prompt ID '{pid}' no encontrado en el set.")
            result.append(by_id[pid])
        return result

    def build_plan(self, backend: str, active_ids: list[str] | None = None) -> PromptPlan:
        """Aplana las clases activas en un PromptPlan ordenado para el backend."""
        from eovrt_media.config.prompt_plan import PromptPhrase, PromptPlan

        phrases: list[PromptPhrase] = []
        seen: dict[str, str] = {}
        idx = 0
        active = self.get_active_classes(active_ids)
        if not active:
            raise ValueError(
                "El plan resultó vacío: no hay clases activas "
                f"(set '{self.resolved_set_id()}', active_ids={active_ids})."
            )
        for cls_ in active:
            # Resolución explícita: una entrada presente pero vacía es un error,
            # no un fallback silencioso a 'default'.
            if backend in cls_.phrasings:
                texts = cls_.phrasings[backend]
            else:
                texts = cls_.phrasings.get("default")
            if not texts:
                raise ValueError(
                    f"Clase '{cls_.id}': phrasings['{backend}'] (o ['default']) "
                    "ausente o vacío."
                )
            for text in texts:
                if text in seen:
                    raise ValueError(
                        f"Texto de prompt duplicado '{text}' "
                        f"(clases '{seen[text]}' y '{cls_.id}')."
                    )
                seen[text] = cls_.id
                phrases.append(
                    PromptPhrase(
                        index=idx,
                        text=text,
                        prompt_id=cls_.id,
                        canonical=cls_.canonical,
                        strategy=cls_.strategy,
                        condition_id=cls_.condition_id,
                    )
                )
                idx += 1
        return PromptPlan(
            set_id=self.resolved_set_id(), backend=backend, phrases=tuple(phrases)
        )


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
    # Unidades iniciales excluidas de los percentiles de G2A (carga de kernels,
    # cache de cuDNN). Se DECLARA en el summary (spec 42 SS5). 0 = comportamiento actual.
    warmup_units: int = 0


# Tipos cuya fuente es una ruta en disco (incluye los alias de video que
# `sources/registry.py` colapsa a 'video_file'). Los tipos vivos (rtsp, oak_d)
# no tienen path.
_PATH_SOURCE_TYPES = {"image_folder", "video", "video_frame", "video_file"}

# Valores válidos de los knobs de oak_d. El schema es la única fuente de verdad
# (falla con 422 en el POST); OakDSource solo mapea estos valores a la API
# DepthAI y verifica en import-time que ambos conjuntos coincidan.
OAK_D_RESOLUTIONS = ("720p", "1080p", "4k")
OAK_D_ORIENTATIONS = ("normal", "rotate_180", "mirror", "flip")


class SourceSection(BaseModel):
    """Sección 'source' de la configuración.

    Puede definirse inline (type + path) o por referencia al catálogo de
    datasets: ``ref: <nombre>`` resuelve ``configs/datasets/<nombre>.yaml``.

    Una fuente viva (rtsp) se identifica por ``url``, no por una ruta en disco:
    para esos tipos ``path`` queda vacío.
    """

    ref: str | None = None
    description: str | None = None

    type: str = "image_folder"
    path: str | None = None
    # Identidad lógica de la fuente para el join aguas abajo (GT del banco de
    # clips por clip_id, claves de escena del control-plane). Default None:
    # sin este knob, el VisualUnit sigue derivando el basename del archivo
    # como hoy (comportamiento inalterado).
    source_id: str | None = None
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

    # Fuente viva OAK-D (DepthAI). `url` = IP fija de la cámara.
    # `resolution`/`fps`/`orientation` solo aplican a source.type=oak_d.
    # orientation: normal | rotate_180 | mirror | flip. La rota el ISP de la
    # cámara (gratis), no la CPU del host. Necesario si está montada invertida.
    resolution: str = "1080p"
    fps: int = Field(default=10, gt=0)
    orientation: str = "normal"

    @model_validator(mode="after")
    def _check_locator(self) -> SourceSection:
        source_type = self.type.lower().strip()
        if source_type == "rtsp":
            if not (self.url or self.path):
                raise ValueError("source.url es requerido para source.type='rtsp'")
        elif source_type == "oak_d":
            if not self.url:
                raise ValueError(
                    "source.url (IP de la cámara, ej. '192.168.1.50') es requerido "
                    "para source.type='oak_d'"
                )
            if self.resolution.lower().strip() not in OAK_D_RESOLUTIONS:
                raise ValueError(
                    f"source.resolution {self.resolution!r} no soportada para oak_d. "
                    f"Opciones: {sorted(OAK_D_RESOLUTIONS)}."
                )
            if self.orientation.lower().strip() not in OAK_D_ORIENTATIONS:
                raise ValueError(
                    f"source.orientation {self.orientation!r} no soportada para oak_d. "
                    f"Opciones: {sorted(OAK_D_ORIENTATIONS)}."
                )
        elif source_type in _PATH_SOURCE_TYPES and not self.path:
            raise ValueError(f"source.path es requerido para source.type={source_type!r}")
        return self


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


class CompressionConfig(BaseModel):
    """Compresión del payload en el transporte de red."""

    codec: str = "jpeg"  # jpeg | raw
    quality: int = 90  # 1-100, solo si codec=jpeg


class TransportConfig(BaseModel):
    """Sección ``transport``: backend del canal productor-consumidor."""

    backend: str = "memory"
    payload_format: str = "uint8_rgb"
    endpoint: str | None = None
    heartbeat_endpoint: str | None = None
    heartbeat_interval_ms: int = Field(default=1000, gt=0)
    heartbeat_timeout_ms: int = Field(default=5000, gt=0)
    request_timeout_ms: int = Field(default=10000, gt=0)
    compression: CompressionConfig = Field(default_factory=CompressionConfig)


class TopologyConfig(BaseModel):
    """Sección ``topology``: disposición de nodos del despliegue."""

    mode: str = "single_host"


class BusConfig(BaseModel):
    """Bus media->control (ADR-003). Apagado por default: el JSONL es la verdad."""

    enabled: bool = False
    endpoint: str = "tcp://0.0.0.0:5557"
    hwm: int = Field(default=1000, gt=0)
    # > 0 bloquea el arranque del run hasta que un SUB se suscriba (spec 40
    # SS3.2 regla 1). 0 = no esperar (comportamiento de un PUB comun).
    wait_for_subscriber_ms: int = Field(default=0, ge=0)


class ModelRuntimeConfig(BaseModel):
    """Knobs de runtime del modelo (rendimiento)."""

    half_precision: bool = True  # fp16 cuando device=cuda; ignorado en cpu
    warmup: bool = True  # inferencia dummy al cargar


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
    runtime: ModelRuntimeConfig = Field(default_factory=ModelRuntimeConfig)

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

    Acepta ``ref`` (catálogo/experimento), ``file`` (ruta explícita) o
    ``set_inline`` (PromptSet embebido — contrato del servicio, Spec A §3.1).
    Precedencia: set_inline > file > ref.
    """

    ref: str | None = None
    file: str | None = None
    set_inline: PromptSet | None = None
    active_ids: list[str] | None = None

    @model_validator(mode="after")
    def require_prompt_source(self) -> PromptsSection:
        if self.ref is None and self.file is None and self.set_inline is None:
            raise ValueError("La sección 'prompts' requiere 'ref', 'file' o 'set_inline'")
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
    save_annotated_video: bool = False
    video_fps: float | None = None

    @model_validator(mode="before")
    @classmethod
    def sync_outputs(cls, data: Any) -> Any:
        if isinstance(data, dict):
            if "run_dir" in data and "base_dir" not in data:
                data["base_dir"] = data["run_dir"]
            elif "base_dir" in data and "run_dir" not in data:
                data["run_dir"] = data["base_dir"]
        return data


class LoggingConfig(BaseModel):
    """Sección 'logging' de la configuración."""

    level: str = "INFO"


class DebugConfig(BaseModel):
    """Debug instrumentation settings."""

    enabled: bool = False


class ExperimentSection(BaseModel):
    """Metadata/provenance del experimento (cross-plano, propagada al run)."""

    id: str | None = None


# ---------------------------------------------------------------------------
# Secret redaction
# ---------------------------------------------------------------------------

# La authority es todo lo que sigue a "//" hasta el primer '/', '?', '#' o el
# final de la cadena. El userinfo (si existe) es todo lo anterior al ÚLTIMO '@'
# dentro de esa authority — un password sin escapar puede contener '@'/':'
# embebidos (p.ej. "p@ss"), así que NO alcanza con cortar en el primer '@'.
#
# `[^/?#]*` es codicioso: intenta consumir toda la authority y retrocede de a un
# carácter hasta encontrar un '@' final, lo que en la práctica ata el match al
# ÚLTIMO '@' anterior a '/', '?', '#' o EOF — exactamente el límite de userinfo.
# Si la authority no contiene ningún '@', el patrón no matchea y no se redacta
# nada (así se preservan `rtsp://host/path` y `rtsp://host/path?foo=a@b`, donde
# el '@' vive en la query, fuera de la authority).
_URL_USERINFO = re.compile(r"//[^/?#]*@")


def redact_url_credentials(url: str) -> str:
    """Redacta userinfo completo de URLs, incluyendo '@'/':' embebidos en el password.

    rtsp://user:pass@host        -> rtsp://***:***@host
    rtsp://user:p@ss@host/path   -> rtsp://***:***@host/path   (sin fugas de "p@ss")
    rtsp://user@host/path        -> rtsp://***:***@host/path   (sin password: se
                                     fabrica un "***:***" fijo por simplicidad; no
                                     sobrevive ningún fragmento del username original)
    rtsp://host/path?foo=a@b     -> sin cambios (el '@' está en la query, no en userinfo)
    """
    return _URL_USERINFO.sub("//***:***@", url)


# ---------------------------------------------------------------------------
# Top-level config
# ---------------------------------------------------------------------------


class RunConfig(BaseModel):
    """Configuración completa de una corrida."""

    run: RunSection
    source: SourceSection
    model: ModelSection
    prompts: PromptsSection
    experiment: ExperimentSection = Field(default_factory=ExperimentSection)

    rate_control: RateControlConfig = Field(default_factory=RateControlConfig)
    transport: TransportConfig = Field(default_factory=TransportConfig)
    topology: TopologyConfig = Field(default_factory=TopologyConfig)
    bus: BusConfig = Field(default_factory=BusConfig)
    postprocess: PostprocessConfig = Field(default_factory=PostprocessConfig)
    outputs: OutputsConfig = Field(default_factory=OutputsConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    debug: DebugConfig = Field(default_factory=DebugConfig)

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
                "debug",
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

    def build_prompt_plan(self, backend: str) -> PromptPlan:
        """Construye el PromptPlan resuelto para el backend del adaptador."""
        if self.prompts_file is None:
            raise RuntimeError("Archivo de prompts no cargado. Usar load_run_config().")
        return self.prompts_file.build_plan(backend, self.prompts.active_ids)

    def get_active_classes(self) -> list[PromptClass]:
        """Clases activas del set (metadata para artefactos/provenance)."""
        if self.prompts_file is None:
            raise RuntimeError("Archivo de prompts no cargado. Usar load_run_config().")
        return self.prompts_file.get_active_classes(self.prompts.active_ids)

    def to_effective_dict(self) -> dict[str, Any]:
        """Devuelve la configuración efectiva como diccionario serializable."""
        data = self.model_dump(exclude={"prompts_file", "config_path"})

        # Redact credentials from source URLs
        source_data = data.get("source")
        if isinstance(source_data, dict):
            for key in ("url", "path"):
                value = source_data.get(key)
                if isinstance(value, str) and "@" in value and "://" in value:
                    source_data[key] = redact_url_credentials(value)

        if self.prompts_file:
            data["resolved_prompt_set"] = self.prompts_file.resolved_set_id()
            data["resolved_prompt_classes"] = [
                {
                    "id": c.id,
                    "canonical": c.canonical,
                    "strategy": c.strategy,
                    "condition_id": c.condition_id,
                }
                for c in self.get_active_classes()
            ]
        return data
