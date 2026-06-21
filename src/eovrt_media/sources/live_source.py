"""LiveSource — fuente viva abstracta (cámara/RTSP). Declarado, no implementado."""

from __future__ import annotations

from eovrt_media.sources.base import BaseSource


class LiveSource(BaseSource):
    """Fuente viva (cámara o RTSP). Interfaz declarada, implementación pendiente."""

    def __iter__(self):
        raise NotImplementedError(
            "source.type=camera/rtsp está declarado pero no implementado. "
            "Usar source.type=image_folder o video_file."
        )

    def __len__(self) -> int:
        return -1  # fuente viva no tiene longitud conocida
