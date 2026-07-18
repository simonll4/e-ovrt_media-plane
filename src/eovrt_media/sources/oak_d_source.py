"""Fuente viva OAK-D Pro PoE vía DepthAI (RGB, conexión por IP fija).

Requiere el SDK DepthAI v2: pip install 'depthai>=2.24,<3' (extra ``edge``).
Conexión SIEMPRE por IP fija/reserva DHCP (dai.DeviceInfo(ip)); el
autodiscovery por broadcast falla bajo WSL (X_LINK_DEVICE_NOT_FOUND).
Ver docs/contexto/oak-d-integration.md.
"""
from __future__ import annotations

import importlib
import json
import logging
import threading
import time
from pathlib import Path
from typing import Any, Iterator

from eovrt_media.config.schemas import (
    OAK_D_ORIENTATIONS,
    OAK_D_RESOLUTIONS,
    OakDPrefilterConfig,
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

# Código del nodo Script (CPython 3.9 en el LEON de la cámara). Solo lógica de
# enrutamiento: nada de píxeles (límite documentado del nodo). Reglas (spec §5):
# reenviar si (1) evidencia de persona en ventana, (2) heartbeat vencido,
# (3) NN muda hace >= stall (fail-open), (4) warm-up sin resultados de NN.
_GATE_SCRIPT_TEMPLATE = '''
import time
import json

CONFIDENCE = __CONFIDENCE__
KEEPALIVE_S = __KEEPALIVE_S__
HEARTBEAT_S = __HEARTBEAT_S__
STALL_S = __STALL_S__
PERSON_LABEL = 1  # person-detection-retail-0013: 0=background, 1=person
STATS_PERIOD_S = 1.0

NEG = -1000000.0
last_person_t = NEG
last_nn_t = NEG
last_sent_t = NEG
nn_results = 0
seen = 0
forwarded = 0
dropped_no_person = 0
by_reason = {"person": 0, "heartbeat": 0, "failopen": 0, "warmup": 0}
last_stats_t = time.monotonic()

while True:
    dets = node.io["detections"].tryGet()
    while dets is not None:
        nn_results += 1
        last_nn_t = time.monotonic()
        for d in dets.detections:
            if d.label == PERSON_LABEL and d.confidence >= CONFIDENCE:
                last_person_t = last_nn_t
                break
        dets = node.io["detections"].tryGet()
    frame = node.io["frames"].get()
    seen += 1
    now = time.monotonic()
    if nn_results == 0:
        reason = "warmup"
    elif now - last_person_t <= KEEPALIVE_S:
        reason = "person"
    elif now - last_nn_t >= STALL_S:
        reason = "failopen"
    elif now - last_sent_t >= HEARTBEAT_S:
        reason = "heartbeat"
    else:
        reason = None
    if reason is None:
        dropped_no_person += 1
    else:
        node.io["out"].send(frame)
        forwarded += 1
        by_reason[reason] += 1
        last_sent_t = now
    if now - last_stats_t >= STATS_PERIOD_S:
        payload = json.dumps({
            "seen": seen,
            "forwarded": forwarded,
            "dropped_no_person": dropped_no_person,
            "forwarded_by_reason": by_reason,
            "nn_results": nn_results,
        }).encode()
        buf = Buffer(len(payload))
        buf.setData(payload)
        node.io["stats"].send(buf)
        last_stats_t = now
'''


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
        isp_scale: tuple[int, int] | None = None,
        xlink_chunk_size: int = 0,
        reconnect_retries: int = 5,
        reconnect_delay_ms: int = 1000,
        max_units: int | None = None,
        source_id: str | None = None,
        prefilter: OakDPrefilterConfig | None = None,
        warmup_frames: int = 0,
        _skip_blob_check: bool = False,
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
        self.isp_scale = tuple(isp_scale) if isp_scale is not None else None
        self.xlink_chunk_size = xlink_chunk_size
        self.reconnect_retries = reconnect_retries
        self.reconnect_delay_ms = reconnect_delay_ms
        self.max_units = max_units
        self.source_id = source_id
        self.warmup_frames = warmup_frames  # el schema valida ge=0
        self.prefilter = prefilter
        self.prefilter_stats: dict | None = None
        self.prefilter_stats_at: float | None = None
        self._skip_blob_check = _skip_blob_check
        self._stop_event = threading.Event()
        if (
            prefilter is not None
            and prefilter.enabled
            and not _skip_blob_check
        ):
            blob = Path(prefilter.model_blob)
            if not blob.is_absolute():
                # Convención de pesos: relativo a la raíz del repo.
                blob = Path(__file__).resolve().parents[3] / prefilter.model_blob
            if not blob.is_file():
                raise FileNotFoundError(
                    f"prefilter.model_blob no encontrado: {blob}. "
                    "Correr `make download-prefilter-blob` (fail-fast: nunca "
                    "degradar en silencio a EN-0)."
                )
            self._blob_path = blob

    # ------------------------------------------------------------------
    # Seams (sobreescribibles en tests con un SDK falso)
    # ------------------------------------------------------------------

    def _render_gate_script(self) -> str:
        """Interpola SOLO números ya validados por el schema (sin inyección)."""
        cfg = self.prefilter
        return (
            _GATE_SCRIPT_TEMPLATE
            .replace("__CONFIDENCE__", repr(float(cfg.confidence)))
            .replace("__KEEPALIVE_S__", repr(cfg.keepalive_window_ms / 1000.0))
            .replace("__HEARTBEAT_S__", repr(cfg.heartbeat_interval_ms / 1000.0))
            .replace("__STALL_S__", repr(cfg.stall_failopen_ms / 1000.0))
        )

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

    def _prefilter_enabled(self) -> bool:
        return self.prefilter is not None and self.prefilter.enabled

    def _no_frame_timeout_s(self) -> float:
        """Con gate activo, un silencio <= heartbeat es normal (spec §6)."""
        if self._prefilter_enabled():
            return max(_NO_FRAME_TIMEOUT_S,
                       3.0 * self.prefilter.heartbeat_interval_ms / 1000.0)
        return _NO_FRAME_TIMEOUT_S

    def _build_camera(self, pipeline: Any, dai: Any) -> Any:
        cam = pipeline.create(dai.node.ColorCamera)
        cam.setBoardSocket(dai.CameraBoardSocket.CAM_A)
        cam.setResolution(
            getattr(dai.ColorCameraProperties.SensorResolution, _RESOLUTIONS[self.resolution])
        )
        cam.setFps(self.fps)
        if self.isp_scale is not None:
            # Escala en el bloque scaler del ISP (hardware, sin SHAVEs); afecta
            # .video y todo lo derivado (spec §7.2).
            cam.setIspScale(*self.isp_scale)
        cam.setInterleaved(False)
        orientation = _ORIENTATIONS[self.orientation]
        if orientation is not None:
            cam.setImageOrientation(getattr(dai.CameraImageOrientation, orientation))
        return cam

    def _build_pipeline(self, dai: Any) -> Any:
        pipeline = dai.Pipeline()
        if self.xlink_chunk_size >= 0:
            # 0 = sin chunking: baseline oficial de baja latencia de Luxonis
            # (spec §7.1). -1 deja el default del device (64 KiB).
            pipeline.setXLinkChunkSize(self.xlink_chunk_size)
        cam = self._build_camera(pipeline, dai)
        xout = pipeline.create(dai.node.XLinkOut)
        xout.setStreamName("rgb")
        if not self._prefilter_enabled():
            cam.video.link(xout.input)
            return pipeline
        # Rama EN-2 (spec §5): preview full-FOV -> NN -> Script gate -> "rgb".
        cam.setPreviewSize(544, 320)          # entrada de retail-0013 (WxH)
        cam.setPreviewKeepAspectRatio(False)  # estirar: no perder bordes del FOV
        nn = pipeline.create(dai.node.MobileNetDetectionNetwork)
        nn.setBlobPath(str(self._blob_path))
        nn.setConfidenceThreshold(self.prefilter.confidence)
        nn.input.setBlocking(False)
        nn.input.setQueueSize(1)              # siempre el frame más fresco
        cam.preview.link(nn.input)
        script = pipeline.create(dai.node.Script)
        script.setScript(self._render_gate_script())
        # frames en modo freshest-only: descartar en la entrada del Script es
        # equivalente al maxSize=1 del host hoy (misma semántica EN-0).
        script.inputs["frames"].setBlocking(False)
        script.inputs["frames"].setQueueSize(1)
        cam.video.link(script.inputs["frames"])
        nn.out.link(script.inputs["detections"])
        script.outputs["out"].link(xout.input)
        xstats = pipeline.create(dai.node.XLinkOut)
        xstats.setStreamName("prefilter_stats")
        script.outputs["stats"].link(xstats.input)
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
        warmed = 0
        failures = 0
        device: Any = None
        queue: Any = None
        stats_queue: Any = None
        last_frame_t = 0.0
        no_frame_timeout = self._no_frame_timeout_s()
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
                            if self._prefilter_enabled():
                                stats_queue = candidate.getOutputQueue(
                                    name="prefilter_stats", maxSize=4, blocking=False
                                )
                        except Exception:
                            candidate.close()
                            raise
                        device = candidate
                        last_frame_t = time.monotonic()
                        # Warm-up por device, no por corrida: (re)abrir el device
                        # reinicia el pipeline dentro de la cámara y el sensor
                        # vuelve a asentar exposición/enfoque, así que cada
                        # reapertura re-descarta warmup_frames.
                        warmed = 0
                    except Exception as exc:
                        failures = self._register_failure(failures, exc)
                        continue
                if stats_queue is not None:
                    try:
                        stats_msg = stats_queue.tryGet()
                    except Exception:
                        stats_msg = None
                    if stats_msg is not None:
                        try:
                            self.prefilter_stats = json.loads(
                                bytes(stats_msg.getData()).decode("utf-8")
                            )
                            self.prefilter_stats_at = time.monotonic()
                        except Exception:
                            logger.warning(
                                "prefilter_stats ilegible; se conserva el último válido"
                            )
                try:
                    msg = queue.tryGet()
                except Exception as exc:
                    device.close()
                    device = None
                    stats_queue = None
                    failures = self._register_failure(failures, exc)
                    continue
                if msg is None:
                    if time.monotonic() - last_frame_t > no_frame_timeout:
                        # Conexión viva pero stream mudo: forzar reconexión.
                        device.close()
                        device = None
                        stats_queue = None
                        failures = self._register_failure(
                            failures,
                            TimeoutError(
                                f"sin frames durante {no_frame_timeout:.0f}s "
                                "con la conexión abierta"
                            ),
                        )
                        continue
                    # Sin frame todavía: esperar respetando el stop event.
                    if self._stop_event.wait(_POLL_INTERVAL_S):
                        return
                    continue
                failures = 0
                last_frame_t = time.monotonic()
                if warmed < self.warmup_frames:
                    # Warm-up del lente: descartar los primeros frames mientras el
                    # sensor asienta exposición/enfoque, ANTES de emitir — y antes
                    # de getCvFrame()/timesync: un frame descartado no paga la
                    # conversión BGR (~6 MB en 1080p) ni la consulta de reloj. No
                    # cuentan para emitted/max_units ni entran al pipeline;
                    # frame_index=0 es el primer frame ya asentado. failures y
                    # last_frame_t ya se resetearon: el watchdog no se dispara
                    # durante el warm-up.
                    warmed += 1
                    continue
                frame = msg.getCvFrame()  # BGR (mismo convenio que cv2/RTSP)
                try:
                    # Timestamp de device ya traducido al steady_clock del host
                    # (timesync <0.5 ms en PoE); clamp a 0 por jitter del sync.
                    delta = dai.Clock.now() - msg.getTimestamp()
                    capture_to_host_ms = round(max(delta.total_seconds() * 1000.0, 0.0), 2)
                except Exception:
                    capture_to_host_ms = None
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
                    capture_to_host_ms=capture_to_host_ms,
                )
                emitted += 1
        finally:
            if device is not None:
                device.close()

    def __len__(self) -> int:
        # Fuente viva sin longitud definida: TypeError deja que list() caiga a
        # iteración pura (mismo razonamiento que RtspSource.__len__).
        raise TypeError("OakDSource is a live camera with no defined length")
