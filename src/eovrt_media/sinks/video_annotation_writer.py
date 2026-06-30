"""Escritor de video anotado — ensambla los frames de una corrida en un .mp4."""

from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path

import cv2
import numpy as np

from eovrt_media.contracts import Detection, RawDetection
from eovrt_media.visualize import annotate_payload_bgr

logger = logging.getLogger(__name__)

_DEFAULT_FPS = 10.0
# cv2 (opencv-python) sólo puede escribir MPEG-4 Part 2 (mp4v), que los reproductores
# embebidos basados en Chromium (VS Code) no decodifican. Escribimos con mp4v y, si hay
# ffmpeg disponible, transcodificamos a H.264 yuv420p (reproducible en navegador/VS Code).
_FOURCC = "mp4v"


class VideoAnnotationWriter:
    """Acumula frames anotados (payload del modelo) y los escribe a un .mp4.

    El FPS de salida se infiere del delta de ``timestamp_ms`` entre los dos primeros
    frames (= fps_origen / stride). Un override explícito (``fps_override``) tiene
    prioridad. Frames de tamaño distinto al de apertura se reescalan a ese tamaño.
    """

    def __init__(
        self,
        output_path: str | Path,
        fps_override: float | None = None,
        default_fps: float = _DEFAULT_FPS,
    ) -> None:
        self.output_path = Path(output_path)
        self.fps_override = fps_override
        self.default_fps = default_fps

        # cv2 escribe a un archivo temporal mp4v; close() lo transcodifica a H.264.
        self._tmp_path = self.output_path.with_name(
            f"{self.output_path.stem}.mp4v{self.output_path.suffix}"
        )
        self._writer: cv2.VideoWriter | None = None
        self._size: tuple[int, int] | None = None  # (width, height)
        self._pending: tuple[np.ndarray, float] | None = None
        self._closed = False

    def add(
        self,
        image_rgb: np.ndarray,
        detections: list[Detection | RawDetection],
        timestamp_ms: float | None,
    ) -> None:
        """Anota un payload RGB y lo agrega al video (apertura diferida del writer)."""
        frame = annotate_payload_bgr(image_rgb, detections)

        if self._writer is not None:
            self._write_frame(frame)
            return

        if self.fps_override is not None:
            self._open(self.fps_override, frame)
            self._write_frame(frame)
            return

        # Sin override: necesitamos dos timestamps para inferir el fps.
        if self._pending is None:
            self._pending = (frame, float(timestamp_ms or 0.0))
            return

        prev_frame, prev_ts = self._pending
        self._pending = None
        delta_ms = float(timestamp_ms or 0.0) - prev_ts
        fps = (1000.0 / delta_ms) if delta_ms > 0 else self.default_fps
        self._open(fps, prev_frame)
        self._write_frame(prev_frame)
        self._write_frame(frame)

    def close(self) -> None:
        """Vacía el frame pendiente (corrida de 1 frame) y libera el writer."""
        if self._closed:
            return
        self._closed = True

        if self._writer is None and self._pending is not None:
            frame, _ = self._pending
            self._pending = None
            self._open(self.default_fps, frame)
            self._write_frame(frame)

        if self._writer is not None:
            self._writer.release()
            self._writer = None
            self._finalize()

    def _finalize(self) -> None:
        """Transcodifica el mp4v temporal a H.264; si no hay ffmpeg, lo deja como está."""
        ffmpeg = shutil.which("ffmpeg")
        if ffmpeg is None:
            self._tmp_path.replace(self.output_path)
            logger.warning(
                "ffmpeg no disponible: %s queda en codec mp4v (puede no reproducirse "
                "en VS Code/navegador).",
                self.output_path,
            )
            return
        result = subprocess.run(
            [
                ffmpeg, "-y", "-loglevel", "error",
                "-i", str(self._tmp_path),
                "-c:v", "libx264", "-pix_fmt", "yuv420p", "-movflags", "+faststart",
                str(self.output_path),
            ],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            self._tmp_path.replace(self.output_path)
            logger.warning(
                "Transcodificación H.264 falló (%s); se conserva mp4v en %s",
                result.stderr.strip(), self.output_path,
            )
            return
        self._tmp_path.unlink(missing_ok=True)
        logger.info(f"Video anotado guardado (H.264): {self.output_path}")

    def _open(self, fps: float, first_frame: np.ndarray) -> None:
        height, width = first_frame.shape[:2]
        self._size = (width, height)
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        fourcc = cv2.VideoWriter_fourcc(*_FOURCC)
        writer = cv2.VideoWriter(str(self._tmp_path), fourcc, fps, self._size)
        if not writer.isOpened():
            raise OSError(f"No se pudo abrir el VideoWriter para: {self._tmp_path}")
        self._writer = writer

    def _write_frame(self, frame: np.ndarray) -> None:
        assert self._writer is not None and self._size is not None
        if (frame.shape[1], frame.shape[0]) != self._size:
            frame = cv2.resize(frame, self._size)
        self._writer.write(frame)
