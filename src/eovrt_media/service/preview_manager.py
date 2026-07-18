"""Sesión de preview singleton: frames en vivo sin persistencia ni bus."""

from __future__ import annotations

import json
import logging
import struct
import threading
import uuid
from dataclasses import dataclass, field
from typing import Any

import cv2
import numpy as np
from PIL import Image

from eovrt_media.config.loader import find_plane_catalog_root, load_run_config_data
from eovrt_media.service.activity_slot import ActivitySlot, SlotBusyError
from eovrt_media.service.preview_request import PreviewRequest, to_run_request
from eovrt_media.service.run_request import to_raw_run_config
from eovrt_media.sources.registry import create_source

logger = logging.getLogger(__name__)

_MAX_WIDTH = 960
_JPEG_QUALITY = 80


class _LatestUnitBox:
    """Entrega solo el último ``VisualUnit`` leído; nunca se acumula un backlog.

    Desacopla la velocidad de captura (gobernada por la fuente: una cámara RTSP
    entrega frames a su propio ritmo, sin esperar a nadie) de la velocidad de
    procesamiento (resize + detección + encode). Con un solo lector serial
    ("for unit in source"), un consumidor más lento que la fuente hace que
    ``cv2.VideoCapture`` acumule su propio buffer interno y cada lectura
    devuelva el frame más VIEJO no consumido — el preview se ve cada vez más
    atrasado, nunca al día (bug real: RTSP mucho más lento que OAK-D, que ya
    trae maxSize=1/blocking=False a nivel de driver). Con esta caja, un hilo
    lector separado drena la fuente todo lo rápido que puede y solo conserva
    el último ``unit``; el consumidor siempre ve el más reciente disponible.
    """

    def __init__(self) -> None:
        self._condition = threading.Condition()
        self._unit: Any = None
        self._done = False
        self._error: BaseException | None = None

    def push(self, unit: Any) -> None:
        with self._condition:
            self._unit = unit
            self._condition.notify()

    def close(self, error: BaseException | None = None) -> None:
        with self._condition:
            self._done = True
            self._error = error
            self._condition.notify()

    def pop_latest(self, timeout: float) -> tuple[Any, bool, BaseException | None]:
        with self._condition:
            self._condition.wait_for(
                lambda: self._unit is not None or self._done, timeout=timeout
            )
            unit, self._unit = self._unit, None
            return unit, self._done, self._error


@dataclass
class _Session:
    preview_id: str
    mode: str
    score_threshold: float | None
    stop_event: threading.Event = field(default_factory=threading.Event)
    source: Any = None
    thread: threading.Thread | None = None
    status: str = "streaming"
    error: str | None = None
    seq: int = 0
    latest: bytes | None = None


class PreviewManager:
    def __init__(self, adapter, model_section, settings, slot: ActivitySlot) -> None:
        self._adapter = adapter
        self._model_section = model_section
        self._settings = settings
        self._slot = slot
        self._lock = threading.Lock()
        self._frame_lock = threading.Lock()
        self._active: _Session | None = None
        self._last_error: str | None = None
        # Última frame emitida por la sesión más reciente: una fuente acotada
        # (image_folder) puede agotarse entre que _loop escribe el último
        # frame y que un poller/WS llama a snapshot(); sin este cache, ese
        # último frame quedaría inalcanzable en cuanto _loop limpia _active.
        self._last_seq: int = 0
        self._last_message: bytes | None = None

    # -- API pública -----------------------------------------------------

    def start(self, request: PreviewRequest) -> str:
        with self._lock:
            if self._active is not None:
                raise SlotBusyError("preview", self._active.preview_id)
            preview_id = f"pv_{uuid.uuid4().hex[:8]}"
            self._slot.acquire("preview", preview_id)
            try:
                raw = to_raw_run_config(to_run_request(request), self._model_section)
                raw.setdefault("outputs", {})["run_dir"] = str(self._settings.runs_dir)
                config = load_run_config_data(
                    raw,
                    plane_root=find_plane_catalog_root(None, self._settings.catalog_root),
                    datasets_root=self._settings.datasets_root,
                )
                source = create_source(config)
                plan = (
                    config.build_prompt_plan(self._adapter.PROMPT_BACKEND)
                    if request.mode == "detect"
                    else None
                )
            except Exception:
                self._slot.release("preview")
                raise
            session = _Session(
                preview_id=preview_id,
                mode=request.mode,
                score_threshold=request.params.score_threshold,
                source=source,
            )
            self._active = session
            self._last_error = None
            self._last_seq = 0
            self._last_message = None
        thread = threading.Thread(
            target=self._loop, args=(session, plan), daemon=True, name="preview-loop"
        )
        session.thread = thread
        thread.start()
        return preview_id

    def stop(self) -> None:
        with self._lock:
            session = self._active
        if session is None:
            return
        session.stop_event.set()
        if session.source is not None:
            session.source.stop()  # cooperativo (mismo patrón que RunControl.request_stop)
        if session.thread is not None:
            session.thread.join(timeout=10.0)

    def is_active(self) -> bool:
        return self._active is not None

    def status(self) -> dict:
        with self._lock:
            session = self._active
            if session is not None:
                return {
                    "status": "streaming",
                    "preview_id": session.preview_id,
                    "mode": session.mode,
                    "error": None,
                }
            if self._last_error is not None:
                return {"status": "error", "preview_id": None, "mode": None, "error": self._last_error}
            return {"status": "idle", "preview_id": None, "mode": None, "error": None}

    def snapshot(self) -> tuple[str, int, bytes | None, str | None]:
        with self._frame_lock:
            session = self._active
            if session is None:
                status = "error" if self._last_error is not None else "idle"
                return status, self._last_seq, self._last_message, self._last_error
            return "streaming", session.seq, session.latest, None

    # -- Loop de captura -------------------------------------------------

    def _loop(self, session: _Session, plan) -> None:
        box = _LatestUnitBox()
        reader = threading.Thread(
            target=self._read_source, args=(session, box), daemon=True, name="preview-reader"
        )
        reader.start()
        try:
            while True:
                unit, done, error = box.pop_latest(timeout=1.0)
                if session.stop_event.is_set():
                    break
                if error is not None:
                    raise error
                if unit is not None:
                    frame = unit.pixel_data
                    if frame is None and unit.path:
                        frame = cv2.imread(unit.path)
                    if frame is not None:
                        frame = self._resize(frame)
                        detections = (
                            self._detect(frame, plan, session.score_threshold) if plan else []
                        )
                        message = self._build_message(
                            session.seq + 1, session.mode, frame, detections, unit
                        )
                        with self._frame_lock:
                            session.seq += 1
                            session.latest = message
                if unit is None and done:
                    break
        except Exception as exc:  # noqa: BLE001
            logger.exception("Preview %s falló", session.preview_id)
            session.status = "error"
            session.error = str(exc)
        finally:
            session.stop_event.set()
            if session.source is not None:
                session.source.stop()  # cooperativo (mismo patrón que RunControl.request_stop)
            reader.join(timeout=10.0)
            with self._lock, self._frame_lock:
                if session.status == "error":
                    self._last_error = session.error
                self._last_seq = session.seq
                self._last_message = session.latest
                if self._active is session:
                    self._active = None
            self._slot.release("preview")

    def _read_source(self, session: _Session, box: _LatestUnitBox) -> None:
        """Drena la fuente todo lo rápido que puede; nunca encola, solo conserva la última."""
        try:
            for unit in session.source:
                if session.stop_event.is_set():
                    return
                box.push(unit)
        except Exception as exc:  # noqa: BLE001
            box.close(error=exc)
            return
        box.close()

    def _resize(self, frame: np.ndarray) -> np.ndarray:
        h, w = frame.shape[:2]
        if w <= _MAX_WIDTH:
            return frame
        scale = _MAX_WIDTH / w
        return cv2.resize(frame, (_MAX_WIDTH, int(h * scale)), interpolation=cv2.INTER_AREA)

    def _detect(self, frame_bgr: np.ndarray, plan, threshold: float | None) -> list[dict]:
        h, w = frame_bgr.shape[:2]
        image = Image.fromarray(cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB))
        raw = self._adapter.predict(image, plan)
        out: list[dict] = []
        for det in raw:
            if threshold is not None and det.score < threshold:
                continue
            x1, y1, x2, y2 = det.box_xyxy
            out.append(
                {
                    "label": det.label,
                    "score": round(float(det.score), 4),
                    "bbox_norm_xyxy": [
                        max(0.0, min(1.0, x1 / w)),
                        max(0.0, min(1.0, y1 / h)),
                        max(0.0, min(1.0, x2 / w)),
                        max(0.0, min(1.0, y2 / h)),
                    ],
                }
            )
        return out

    def _build_message(self, seq: int, mode: str, frame: np.ndarray, detections: list[dict], unit) -> bytes:
        ok, jpeg = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), _JPEG_QUALITY])
        if not ok:
            raise RuntimeError("No se pudo codificar el frame a JPEG")
        h, w = frame.shape[:2]
        header = json.dumps(
            {
                "seq": seq,
                "ts": unit.capture_wallclock_ms,
                "width": w,
                "height": h,
                "mode": mode,
                "detections": detections,
                "unit_id": unit.unit_id,
            }
        ).encode("utf-8")
        return struct.pack(">I", len(header)) + header + jpeg.tobytes()
