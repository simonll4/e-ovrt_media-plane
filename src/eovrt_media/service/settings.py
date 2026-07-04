"""Configuración del servicio desde variables de entorno EOVRT_*."""
from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ServiceSettings:
    model_ref: str
    model_device: str | None
    runs_dir: Path
    datasets_root: Path | None
    catalog_root: Path | None
    watchdog_seconds: float
    retention_max_age_days: float | None
    retention_max_total_gb: float | None
    shutdown_grace_seconds: float
    eval_iou_threshold: float = 0.5

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> ServiceSettings:
        env = os.environ if env is None else env
        model_ref = env.get("EOVRT_MODEL_REF")
        if not model_ref:
            raise ValueError(
                "EOVRT_MODEL_REF es obligatorio (p.ej. 'mock' o 'grounding-dino/gdino-tiny')"
            )

        def _path(key: str) -> Path | None:
            value = env.get(key)
            return Path(value) if value else None

        def _float(key: str) -> float | None:
            value = env.get(key)
            return float(value) if value else None

        return cls(
            model_ref=model_ref,
            model_device=env.get("EOVRT_MODEL_DEVICE") or None,
            runs_dir=Path(env.get("EOVRT_RUNS_DIR", "runs")),
            datasets_root=_path("EOVRT_DATASETS_ROOT"),
            catalog_root=_path("EOVRT_MEDIA_CATALOG_ROOT"),
            watchdog_seconds=float(env.get("EOVRT_WATCHDOG_SECONDS", "120")),
            retention_max_age_days=_float("EOVRT_RUNS_MAX_AGE_DAYS"),
            retention_max_total_gb=_float("EOVRT_RUNS_MAX_TOTAL_GB"),
            shutdown_grace_seconds=float(env.get("EOVRT_SHUTDOWN_GRACE_SECONDS", "20")),
            eval_iou_threshold=float(env.get("EOVRT_EVAL_IOU_THRESHOLD", "0.5")),
        )
