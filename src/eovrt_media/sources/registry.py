"""Registro explícito de plugins de ingesta visual (Spec A §5)."""
from __future__ import annotations

import importlib.util
from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING

from eovrt_media.config.schemas import LIVE_SOURCE_TYPES
from eovrt_media.sources import BaseSource, ImageFolderSource, VideoFileSource

if TYPE_CHECKING:
    from eovrt_media.config import RunConfig

# La disponibilidad de oak_d depende de que el SDK DepthAI esté instalado
# (extra opcional `edge`). El flag `available` es la fuente de verdad que
# consumen el catálogo y el gate 4xx del run request: hardcodearlo en True
# haría que una build sin depthai anuncie un plugin que solo puede fallar.
_DEPTHAI_AVAILABLE = importlib.util.find_spec("depthai") is not None


class PluginUnavailableError(ValueError):
    """El plugin existe en el registro pero no está disponible en esta build."""


@dataclass(frozen=True)
class IngestPlugin:
    id: str
    kind: str  # bounded | live
    available: bool
    description: str


PLUGINS: dict[str, IngestPlugin] = {
    "image_folder": IngestPlugin("image_folder", "bounded", True, "Carpeta de imágenes (datasets)"),
    "video_file": IngestPlugin("video_file", "bounded", True, "Archivo de video local"),
    "rtsp": IngestPlugin("rtsp", "live", True, "Stream RTSP (cámara IP)"),
    "oak_d": IngestPlugin(
        "oak_d",
        "live",
        _DEPTHAI_AVAILABLE,
        "OAK-D Pro PoE (RGB vía DepthAI, IP fija)"
        if _DEPTHAI_AVAILABLE
        else "OAK-D Pro PoE (requiere el SDK DepthAI: pip install -e '.[edge]')",
    ),
}

_VIDEO_ALIASES = {"video", "video_frame", "video_file"}

# El schema valida warmup_frames contra LIVE_SOURCE_TYPES; este registro declara
# kind="live" por plugin. Si divergen, un plugin vivo nuevo validaría 422 (o al
# revés: aceptaría el knob y lo ignoraría en silencio). Verificación import-time,
# mismo patrón que OAK_D_RESOLUTIONS en OakDSource.
assert {p.id for p in PLUGINS.values() if p.kind == "live"} == set(LIVE_SOURCE_TYPES)


def list_plugins() -> list[dict]:
    return [asdict(p) for p in PLUGINS.values()]


def create_source(config: "RunConfig") -> BaseSource:
    """Crea una fuente; RateGate aplica el stride después de la ingesta."""
    source_type = config.source.type.lower().strip()
    plugin_id = "video_file" if source_type in _VIDEO_ALIASES else source_type
    plugin = PLUGINS.get(plugin_id)
    if plugin is None:
        raise ValueError(
            f"Tipo de fuente '{source_type}' no soportado. "
            f"Plugins: {sorted(PLUGINS)}."
        )
    if not plugin.available:
        raise PluginUnavailableError(
            f"Plugin de ingesta '{plugin_id}' no disponible: {plugin.description}"
        )
    if plugin_id == "image_folder":
        return ImageFolderSource(
            folder_path=config.source.path,
            extensions=config.source.extensions,
            every_n=1,
            max_units=config.run.max_units,
            source_id=config.source.source_id,
        )
    if plugin_id == "video_file":
        return VideoFileSource(
            video_path=config.source.path,
            every_n=1,
            target_fps=None,
            max_units=config.run.max_units,
            source_id=config.source.source_id,
        )
    if plugin_id == "rtsp":
        from eovrt_media.sources import RtspSource

        return RtspSource(
            url=config.source.url or config.source.path,
            reconnect_retries=config.source.reconnect_retries,
            reconnect_delay_ms=config.source.reconnect_delay_ms,
            max_units=config.run.max_units,
            source_id=config.source.source_id,
            warmup_frames=config.source.warmup_frames,
        )
    if plugin_id == "oak_d":
        from eovrt_media.sources import OakDSource

        return OakDSource(
            url=config.source.url,
            resolution=config.source.resolution,
            fps=config.source.fps,
            orientation=config.source.orientation,
            isp_scale=config.source.isp_scale,
            xlink_chunk_size=config.source.xlink_chunk_size,
            reconnect_retries=config.source.reconnect_retries,
            reconnect_delay_ms=config.source.reconnect_delay_ms,
            max_units=config.run.max_units,
            source_id=config.source.source_id,
            prefilter=config.source.prefilter,
            warmup_frames=config.source.warmup_frames,
        )
    # Inalcanzable con PLUGINS actual; protege al próximo plugin que se agregue
    # al registro sin su rama correspondiente acá.
    raise ValueError(f"Plugin '{plugin_id}' registrado pero sin constructor en create_source.")
