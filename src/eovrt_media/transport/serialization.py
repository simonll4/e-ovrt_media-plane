"""Serialización de NormalizedUnit y mensajes de control para el wire ZeroMQ.

Formato de un frame de datos:
  [4 bytes big-endian: header_len][header_len bytes: msgpack(meta)][payload crudo]
El payload se reconstruye con dtype derivado de payload_format y shape de target_size.
"""
from __future__ import annotations

import logging
import struct

import cv2
import msgpack
import numpy as np

from eovrt_media.contracts.normalized_unit import (
    NormalizedUnit, PayloadFormat, ResizeTransform,
)

logger = logging.getLogger(__name__)

# Mensajes de control (prefijo reservado que nunca aparece en un header válido)
REQUEST = b"\x00CTRL:REQUEST"
END_MSG = b"\x00CTRL:END"
HEARTBEAT = b"\x00CTRL:HEARTBEAT"

_CONTROL_PREFIX = b"\x00CTRL:"

_DTYPE_BY_FORMAT = {
    PayloadFormat.UINT8_RGB: np.uint8,
    PayloadFormat.FP32: np.float32,
}


def is_control(data: bytes) -> bool:
    """True si el mensaje es de control (REQUEST/END/HEARTBEAT)."""
    return data.startswith(_CONTROL_PREFIX)


def serialize_unit(unit: NormalizedUnit, codec: str = "raw", quality: int = 90) -> bytes:
    """Empaqueta una NormalizedUnit como header msgpack + payload (raw o JPEG)."""
    meta = {
        "run_id": unit.run_id,
        "unit_id": unit.unit_id,
        "source_id": unit.source_id,
        "source_path": unit.source_path,
        "frame_index": unit.frame_index,
        "timestamp_ms": unit.timestamp_ms,
        "orig_width": unit.orig_width,
        "orig_height": unit.orig_height,
        "payload_format": unit.payload_format.value,
        "target_size": list(unit.target_size),
        "transform": {
            "scale_x": unit.transform.scale_x,
            "scale_y": unit.transform.scale_y,
            "pad_x": unit.transform.pad_x,
            "pad_y": unit.transform.pad_y,
        },
    }
    if codec == "jpeg" and unit.payload_format == PayloadFormat.UINT8_RGB:
        ok, buf = cv2.imencode(".jpg", unit.payload, [int(cv2.IMWRITE_JPEG_QUALITY), int(quality)])
        if not ok:
            raise ValueError("cv2.imencode falló al comprimir el payload a JPEG")
        payload_bytes = buf.tobytes()
        meta["payload_codec"] = "jpeg"
    else:
        if codec == "jpeg":
            logger.warning(
                "codec=jpeg ignorado para payload_format=%s; usando raw",
                unit.payload_format.value,
            )
        payload_bytes = np.ascontiguousarray(unit.payload).tobytes()
        meta["payload_codec"] = "raw"
    header = msgpack.packb(meta, use_bin_type=True)
    return struct.pack(">I", len(header)) + header + payload_bytes


def deserialize_unit(data: bytes) -> NormalizedUnit:
    """Reconstruye una NormalizedUnit desde el formato de wire (raw o JPEG)."""
    (header_len,) = struct.unpack(">I", data[:4])
    header = data[4 : 4 + header_len]
    payload_bytes = data[4 + header_len :]
    meta = msgpack.unpackb(header, raw=False)

    fmt = PayloadFormat(meta["payload_format"])
    target_h, target_w = meta["target_size"]
    codec = meta.get("payload_codec", "raw")

    if codec == "jpeg":
        payload = cv2.imdecode(np.frombuffer(payload_bytes, dtype=np.uint8), cv2.IMREAD_COLOR)
        if payload is None:
            raise ValueError("cv2.imdecode falló al descomprimir el payload JPEG")
    else:
        dtype = _DTYPE_BY_FORMAT[fmt]
        payload = np.frombuffer(payload_bytes, dtype=dtype).reshape((target_h, target_w, 3)).copy()

    t = meta["transform"]
    return NormalizedUnit(
        run_id=meta["run_id"],
        unit_id=meta["unit_id"],
        source_id=meta["source_id"],
        source_path=meta["source_path"],
        frame_index=meta["frame_index"],
        timestamp_ms=meta["timestamp_ms"],
        orig_width=meta["orig_width"],
        orig_height=meta["orig_height"],
        payload=payload,
        payload_format=fmt,
        target_size=(target_h, target_w),
        transform=ResizeTransform(
            scale_x=t["scale_x"], scale_y=t["scale_y"], pad_x=t["pad_x"], pad_y=t["pad_y"]
        ),
    )
