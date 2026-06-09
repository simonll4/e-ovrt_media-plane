"""Módulo de contratos de datos del plano de medios E-OVRT."""

from eovrt_media.contracts.visual_unit import VisualUnit
from eovrt_media.contracts.detection import RawDetection, Detection
from eovrt_media.contracts.events import DetectionEvent, RunSummary
from eovrt_media.contracts.metrics import MetricSample
from eovrt_media.contracts.errors import ErrorEvent

__all__ = [
    "VisualUnit",
    "RawDetection",
    "Detection",
    "DetectionEvent",
    "RunSummary",
    "MetricSample",
    "ErrorEvent",
]
