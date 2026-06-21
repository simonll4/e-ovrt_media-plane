"""Etapa de normalización espacial del productor + finalizador tensorial del consumidor."""

from __future__ import annotations

import cv2
import numpy as np

from eovrt_media.contracts import VisualUnit
from eovrt_media.contracts.normalized_unit import (
    NormalizedUnit, PayloadFormat, ResizeTransform
)
from eovrt_media.models.base import ModelInputSpec


def _letterbox(
    img: np.ndarray, target_h: int, target_w: int
) -> tuple[np.ndarray, ResizeTransform]:
    """Resize con letterbox (aspecto preservado + padding) a (target_h, target_w)."""
    h, w = img.shape[:2]
    scale = min(target_w / w, target_h / h)
    new_w, new_h = int(round(w * scale)), int(round(h * scale))
    resized = cv2.resize(img, (new_w, new_h), interpolation=cv2.INTER_LINEAR)
    canvas = np.zeros((target_h, target_w, 3), dtype=np.uint8)
    pad_y = (target_h - new_h) // 2
    pad_x = (target_w - new_w) // 2
    canvas[pad_y : pad_y + new_h, pad_x : pad_x + new_w] = resized
    return canvas, ResizeTransform(
        scale_x=scale, scale_y=scale, pad_x=float(pad_x), pad_y=float(pad_y)
    )


def normalize_spatial(
    unit: VisualUnit,
    spec: ModelInputSpec,
    payload_format: PayloadFormat,
) -> NormalizedUnit:
    """Normalización espacial (producer-side): carga imagen, RGB, resize, NormalizedUnit.

    Args:
        unit: Unidad visual de entrada (contiene path a la imagen).
        spec: Especificaciones del modelo (target_size, resize_mode).
        payload_format: Formato del payload resultante.

    Returns:
        NormalizedUnit con el payload redimensionado y el transform aplicado.
    """
    if payload_format == PayloadFormat.FP16:
        raise NotImplementedError(
            "payload_format=fp16 is declared but not implemented; "
            "implement it together with the backend network."
        )

    # Cargar imagen en RGB
    img_bgr = cv2.imread(unit.path)
    if img_bgr is None:
        raise FileNotFoundError(f"No se pudo leer la imagen: {unit.path}")
    img_rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)

    target_h, target_w = spec.target_size

    if spec.resize_mode == "letterbox":
        payload, transform = _letterbox(img_rgb, target_h, target_w)
    else:
        # Resize directo (stretch)
        h, w = img_rgb.shape[:2]
        scale_x = target_w / w
        scale_y = target_h / h
        payload = cv2.resize(img_rgb, (target_w, target_h), interpolation=cv2.INTER_LINEAR)
        transform = ResizeTransform(
            scale_x=scale_x, scale_y=scale_y, pad_x=0.0, pad_y=0.0
        )

    if payload_format == PayloadFormat.FP32:
        payload = payload.astype(np.float32) / 255.0

    return NormalizedUnit(
        unit_id=unit.unit_id,
        source_id=getattr(unit, "source_id", None),
        frame_index=getattr(unit, "frame_index", None),
        timestamp_ms=getattr(unit, "timestamp_ms", None),
        orig_width=unit.width,
        orig_height=unit.height,
        payload=payload,
        payload_format=payload_format,
        target_size=(target_h, target_w),
        transform=transform,
        run_id=unit.run_id,
    )


def prepare_model_input(
    unit: NormalizedUnit, spec: ModelInputSpec, device: str = "cpu"
) -> "torch.Tensor":  # noqa: F821
    """Finalización tensorial (consumer-side): uint8→float, mean/std, HWC→CHW, device.

    Args:
        unit: Unidad normalizada espacialmente.
        spec: Especificaciones del modelo (mean, std).
        device: Dispositivo PyTorch destino (e.g. "cpu", "cuda").

    Returns:
        Tensor BCHW float32 listo para inferencia.
    """
    import torch

    arr = unit.payload
    if arr.dtype == np.uint8:
        tensor = torch.from_numpy(arr).float() / 255.0
    else:
        tensor = torch.from_numpy(arr.copy()).float()

    mean = torch.tensor(spec.mean, dtype=torch.float32)
    std = torch.tensor(spec.std, dtype=torch.float32)
    tensor = (tensor - mean) / std   # HWC
    tensor = tensor.permute(2, 0, 1)  # CHW
    tensor = tensor.unsqueeze(0)      # BCHW
    return tensor.to(device)
