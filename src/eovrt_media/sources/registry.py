"""Registro explícito de plugins de ingesta visual (Spec A §5)."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING

from eovrt_media.sources import BaseSource, ImageFolderSource, VideoFileSource

if TYPE_CHECKING:
    from eovrt_media.config import RunConfig


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
    "oak_d": IngestPlugin("oak_d", "live", False, "OAK-D Pro PoE (hardware no disponible)"),
}

_VIDEO_ALIASES = {"video", "video_frame", "video_file"}


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
        )
    if plugin_id == "video_file":
        return VideoFileSource(
            video_path=config.source.path,
            every_n=1,
            target_fps=None,
            max_units=config.run.max_units,
        )
    # rtsp (live)
    from eovrt_media.sources import RtspSource

    return RtspSource(
        url=config.source.url or config.source.path,
        reconnect_retries=config.source.reconnect_retries,
        reconnect_delay_ms=config.source.reconnect_delay_ms,
        max_units=config.run.max_units,
    )
