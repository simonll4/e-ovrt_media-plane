"""Fuente viva RTSP — cámara IP estándar (EZVIZ, Hikvision, etc.)."""
from __future__ import annotations

import logging
import time
from typing import Iterator

import cv2

from eovrt_media.contracts import VisualUnit
from eovrt_media.sources.base import BaseSource

logger = logging.getLogger(__name__)


class RtspSource(BaseSource):
    """Lee un stream RTSP y produce VisualUnits con timestamp de captura.

    A diferencia de VideoFileSource: nunca hace looping, marca el timestamp con
    el reloj de pared al capturar (hace significativo max_staleness_ms), y
    reintenta la conexión ante cortes de red.
    """

    def __init__(
        self,
        url: str,
        reconnect_retries: int = 5,
        reconnect_delay_ms: int = 1000,
        max_units: int | None = None,
    ) -> None:
        self.url = url
        self.reconnect_retries = reconnect_retries
        self.reconnect_delay_ms = reconnect_delay_ms
        self.max_units = max_units

    def _open_capture(self, url: str) -> cv2.VideoCapture:
        """Abre la captura RTSP. Sobreescribible en tests para usar un archivo."""
        return cv2.VideoCapture(url)

    def _connect(self) -> cv2.VideoCapture:
        """Intenta abrir la captura con reintentos; lanza ConnectionError al agotar."""
        for attempt in range(1, self.reconnect_retries + 1):
            cap = self._open_capture(self.url)
            if cap.isOpened():
                return cap
            cap.release()
            logger.warning(
                "RTSP no disponible (intento %d/%d): %s",
                attempt, self.reconnect_retries, self.url,
            )
            if attempt < self.reconnect_retries and self.reconnect_delay_ms > 0:
                time.sleep(self.reconnect_delay_ms / 1000.0)
        raise ConnectionError(
            f"RTSP: no se pudo conectar tras {self.reconnect_retries} intentos: {self.url}"
        )

    def __iter__(self) -> Iterator[VisualUnit]:
        cap = self._connect()
        emitted = 0
        try:
            while True:
                if self.max_units is not None and emitted >= self.max_units:
                    return
                ok, frame = cap.read()
                if not ok:
                    cap.release()
                    cap = self._connect()  # reintenta; lanza si agota
                    ok, frame = cap.read()
                    if not ok:
                        return  # fin de stream tras reconexión
                height, width = frame.shape[:2]
                timestamp_ms = time.time() * 1000.0
                yield VisualUnit(
                    unit_id=f"frame_{emitted:06d}",
                    source_path=self.url,
                    source_type="video_frame",
                    frame_index=emitted,
                    width=width,
                    height=height,
                    timestamp_ms=round(timestamp_ms, 2),
                    pixel_data=frame,  # BGR; evita que image_loader reabra el stream
                )
                emitted += 1
        finally:
            cap.release()

    def __len__(self) -> int:
        # A live RTSP stream has no defined length.
        # Raising TypeError here lets list() fall back to pure __iter__ iteration
        # (CPython behaviour: list() skips pre-allocation on TypeError from __len__).
        # Returning -1 or sys.maxsize would violate Python's __len__ >= 0 contract
        # (enforced since CPython 3.9) or cause MemoryError in list().
        raise TypeError("RtspSource is a live stream with no defined length")
