"""Fuente viva OAK-D Pro PoE vía DepthAI (RGB, conexión por IP fija).

Requiere el SDK DepthAI v2: pip install 'depthai>=2.24,<3' (extra ``edge``).
Conexión SIEMPRE por IP fija/reserva DHCP (dai.DeviceInfo(ip)); el
autodiscovery por broadcast falla bajo WSL (X_LINK_DEVICE_NOT_FOUND).
Ver docs/contexto/oak-d-integration.md.
"""
from __future__ import annotations

import importlib
import logging
import threading
import time
from typing import Any, Iterator

from eovrt_media.config.schemas import (
    OAK_D_ORIENTATIONS,
    OAK_D_RESOLUTIONS,
    redact_url_credentials,
)
from eovrt_media.contracts import VisualUnit
from eovrt_media.sources.base import BaseSource

logger = logging.getLogger(__name__)

# resolution del config -> atributo de dai.ColorCameraProperties.SensorResolution
_RESOLUTIONS = {"720p": "THE_720_P", "1080p": "THE_1080_P", "4k": "THE_4_K"}

# orientation del config -> atributo de dai.CameraImageOrientation. La rotación la
# hace el ISP de la cámara, no la CPU del host: es gratis. "normal" no toca el sensor.
_ORIENTATIONS = {
    "normal": None,
    "rotate_180": "ROTATE_180_DEG",
    "mirror": "HORIZONTAL_MIRROR",
    "flip": "VERTICAL_FLIP",
}

# Los valores válidos los declara el schema (única fuente de verdad para el 422
# del POST); estos mapas solo traducen a nombres de la API DepthAI.
assert set(_RESOLUTIONS) == set(OAK_D_RESOLUTIONS)
assert set(_ORIENTATIONS) == set(OAK_D_ORIENTATIONS)

# Espera entre sondeos de la cola cuando no hay frame: corta para que stop()
# tenga latencia baja, sin busy-loop.
_POLL_INTERVAL_S = 0.01

# Watchdog de stream mudo: conexión TCP viva pero cola que no entrega frames
# (pipeline colgado dentro de la cámara). Pasado este tiempo sin frames se
# fuerza la reconexión — a diferencia de RTSP, acá tryGet() no falla solo.
_NO_FRAME_TIMEOUT_S = 10.0


class OakDSource(BaseSource):
    """Lee el stream RGB de una OAK-D Pro PoE y produce VisualUnits.

    Igual que RtspSource: fuente viva con timestamp de reloj de pared (hace
    significativo max_staleness_ms), parada cooperativa vía stop() y
    reconexión con reintentos. El device DepthAI se abre y se cierra SIEMPRE
    dentro de __iter__ (hilo productor): stop() solo setea un evento.
    """

    SOURCE_CLOCK = "wallclock"

    def __init__(
        self,
        url: str,
        resolution: str = "1080p",
        fps: int = 10,
        orientation: str = "normal",
        reconnect_retries: int = 5,
        reconnect_delay_ms: int = 1000,
        max_units: int | None = None,
        source_id: str | None = None,
    ) -> None:
        if not url:
            raise ValueError(
                "OakDSource requiere url = IP de la cámara (ej. '192.168.1.50', "
                "reservada por DHCP en el router)."
            )
        orientation_key = str(orientation).lower().strip()
        if orientation_key not in _ORIENTATIONS:
            raise ValueError(
                f"orientation {orientation!r} no soportada para oak_d. "
                f"Opciones: {sorted(_ORIENTATIONS)}."
            )
        resolution_key = str(resolution).lower().strip()
        if resolution_key not in _RESOLUTIONS:
            raise ValueError(
                f"resolution {resolution!r} no soportada para oak_d. "
                f"Opciones: {sorted(_RESOLUTIONS)}."
            )
        if fps <= 0:
            raise ValueError(f"fps debe ser > 0 para oak_d (recibido: {fps}).")
        self.url = url
        self.resolution = resolution_key
        self.fps = fps
        self.orientation = orientation_key
        self.reconnect_retries = reconnect_retries
        self.reconnect_delay_ms = reconnect_delay_ms
        self.max_units = max_units
        self.source_id = source_id
        self._stop_event = threading.Event()

    # ------------------------------------------------------------------
    # Seams (sobreescribibles en tests con un SDK falso)
    # ------------------------------------------------------------------

    def _load_sdk(self) -> Any:
        """Import lazy de depthai: el servicio no lo requiere si no usa oak_d."""
        try:
            return importlib.import_module("depthai")
        except ImportError as exc:
            raise ImportError(
                "OakDSource (source.type=oak_d) requiere el SDK DepthAI: "
                "pip install 'depthai>=2.24,<3' (o pip install -e '.[edge]')."
            ) from exc

    def _open_device(self, dai: Any) -> Any:
        """Conecta por IP fija (nunca autodiscovery: falla bajo WSL)."""
        return dai.Device(self._build_pipeline(dai), dai.DeviceInfo(self.url))

    # ------------------------------------------------------------------

    def _build_pipeline(self, dai: Any) -> Any:
        pipeline = dai.Pipeline()
        cam = pipeline.create(dai.node.ColorCamera)
        cam.setBoardSocket(dai.CameraBoardSocket.CAM_A)
        cam.setResolution(
            getattr(dai.ColorCameraProperties.SensorResolution, _RESOLUTIONS[self.resolution])
        )
        cam.setFps(self.fps)
        cam.setInterleaved(False)
        orientation = _ORIENTATIONS[self.orientation]
        if orientation is not None:
            cam.setImageOrientation(getattr(dai.CameraImageOrientation, orientation))
        xout = pipeline.create(dai.node.XLinkOut)
        xout.setStreamName("rgb")
        cam.video.link(xout.input)
        return pipeline

    def stop(self) -> None:
        """Interrumpe el bucle de captura tras el frame actual."""
        self._stop_event.set()

    def _register_failure(self, failures: int, exc: Exception) -> int:
        """Cuenta un fallo consecutivo; lanza ConnectionError al agotar.

        NUNCA exponer la URL cruda: si trajera credenciales embebidas se
        filtrarían a logs y a errors.jsonl, que la API sirve sin autenticación
        (misma regla que RtspSource). El backoff espera sobre el stop event,
        no con time.sleep: un stop() durante un corte de red corta al instante.
        """
        failures += 1
        safe_url = redact_url_credentials(self.url)
        logger.warning(
            "OAK-D no disponible (intento %d/%d) en %s: %s",
            failures, self.reconnect_retries, safe_url, exc,
        )
        if failures >= self.reconnect_retries:
            raise ConnectionError(
                f"OAK-D: no se pudo conectar tras {self.reconnect_retries} "
                f"intentos: {safe_url}"
            ) from exc
        if self.reconnect_delay_ms > 0:
            self._stop_event.wait(self.reconnect_delay_ms / 1000.0)
        return failures

    def __iter__(self) -> Iterator[VisualUnit]:
        dai = self._load_sdk()
        emitted = 0
        failures = 0
        device: Any = None
        queue: Any = None
        last_frame_t = 0.0
        try:
            while True:
                if self._stop_event.is_set():
                    return
                if self.max_units is not None and emitted >= self.max_units:
                    return
                if device is None:
                    # Invariante: device != None implica queue de ESTE device.
                    # Si getOutputQueue falla, el device recién abierto se
                    # cierra acá mismo — dejarlo abierto con la cola del
                    # anterior produce livelock sin reconexión.
                    try:
                        candidate = self._open_device(dai)
                        try:
                            # maxSize=1: el device retiene solo el frame más
                            # fresco y descarta los viejos gratis. Una cola más
                            # profunda sirve frames de hasta N períodos de
                            # antigüedad con timestamp de dequeue fresco, y esa
                            # staleness queda invisible para bounded_freshness.
                            queue = candidate.getOutputQueue(
                                name="rgb", maxSize=1, blocking=False
                            )
                        except Exception:
                            candidate.close()
                            raise
                        device = candidate
                        last_frame_t = time.monotonic()
                    except Exception as exc:
                        failures = self._register_failure(failures, exc)
                        continue
                try:
                    msg = queue.tryGet()
                except Exception as exc:
                    device.close()
                    device = None
                    failures = self._register_failure(failures, exc)
                    continue
                if msg is None:
                    if time.monotonic() - last_frame_t > _NO_FRAME_TIMEOUT_S:
                        # Conexión viva pero stream mudo: forzar reconexión.
                        device.close()
                        device = None
                        failures = self._register_failure(
                            failures,
                            TimeoutError(
                                f"sin frames durante {_NO_FRAME_TIMEOUT_S:.0f}s "
                                "con la conexión abierta"
                            ),
                        )
                        continue
                    # Sin frame todavía: esperar respetando el stop event.
                    if self._stop_event.wait(_POLL_INTERVAL_S):
                        return
                    continue
                frame = msg.getCvFrame()  # BGR (mismo convenio que cv2/RTSP)
                failures = 0
                last_frame_t = time.monotonic()
                height, width = frame.shape[:2]
                timestamp_ms = time.time() * 1000.0
                yield VisualUnit(
                    unit_id=f"frame_{emitted:06d}",
                    source_id=self.source_id,
                    source_path=self.url,
                    source_type="video_frame",
                    frame_index=emitted,
                    width=width,
                    height=height,
                    timestamp_ms=round(timestamp_ms, 2),
                    pixel_data=frame,  # evita que image_loader reabra la fuente
                    source_clock=self.SOURCE_CLOCK,
                )
                emitted += 1
        finally:
            if device is not None:
                device.close()

    def __len__(self) -> int:
        # Fuente viva sin longitud definida: TypeError deja que list() caiga a
        # iteración pura (mismo razonamiento que RtspSource.__len__).
        raise TypeError("OakDSource is a live camera with no defined length")
