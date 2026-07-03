"""Retención de RUNS_DIR: GC por antigüedad y tamaño total (Spec A §7.4)."""
from __future__ import annotations

import logging
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path

from eovrt_media.service.settings import ServiceSettings
from eovrt_media.sinks.jsonl_sink import atomic_write_json

logger = logging.getLogger(__name__)


def _dir_size_bytes(path: Path) -> int:
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file())


def gc_runs_dir(settings: ServiceSettings, *, exclude: set[str] | None = None) -> list[str]:
    runs_dir = settings.runs_dir
    if not runs_dir.is_dir():
        return []
    exclude = exclude or set()
    removed: list[str] = []
    dirs = sorted(
        (d for d in runs_dir.iterdir() if d.is_dir() and d.name not in exclude),
        key=lambda d: d.stat().st_mtime,
    )
    if settings.retention_max_age_days is not None:
        cutoff = time.time() - settings.retention_max_age_days * 86400
        for d in list(dirs):
            if d.stat().st_mtime < cutoff:
                shutil.rmtree(d, ignore_errors=True)
                removed.append(d.name)
                dirs.remove(d)
    if settings.retention_max_total_gb is not None:
        limit = settings.retention_max_total_gb * 1024**3
        sizes = {d: _dir_size_bytes(d) for d in dirs}
        total = sum(sizes.values())
        for d in list(dirs):  # más viejo primero
            if total <= limit:
                break
            shutil.rmtree(d, ignore_errors=True)
            removed.append(d.name)
            total -= sizes[d]
    return removed


def reconcile_orphan_runs(settings: ServiceSettings) -> list[str]:
    """Detecta run dirs huérfanos (el proceso murió con un run activo —
    kill/OOM— antes de que ``RunManager._finalize`` pudiera escribir
    ``summary.json``) y les escribe un summary mínimo con
    ``status: "interrupted"``.

    Sin esto, ``RunManager.list_runs()``/``get()`` omiten (o 404-ean) estos
    runs porque requieren ``summary.json``, y sus artefactos parciales
    (detections/metrics) quedan ocupando disco indefinidamente, invisibles
    para la API.

    Idempotente: un run dir que YA tiene ``summary.json`` (incluyendo uno
    escrito por una reconciliación previa) no se toca.
    """
    runs_dir = settings.runs_dir
    if not runs_dir.is_dir():
        return []
    reconciled: list[str] = []
    for d in sorted(runs_dir.iterdir()):
        if not d.is_dir():
            continue
        summary_path = d / "summary.json"
        if summary_path.exists():
            continue
        try:
            mtime = d.stat().st_mtime
        except OSError:
            mtime = time.time()
        interrupted_at = datetime.fromtimestamp(mtime, tz=timezone.utc).isoformat()
        summary = {
            "run_id": d.name,
            "status": "interrupted",
            "stop_cause": "process_died",
            "error": (
                "El proceso del servicio terminó (kill/OOM/crash) con este run "
                "activo, antes de poder finalizar y escribir su summary.json; "
                "reconciliado al arrancar el servicio."
            ),
            "finished_at": interrupted_at,
        }
        atomic_write_json(summary_path, summary)
        logger.warning(
            "Run huérfano reconciliado: %s (dir mtime=%s) -> status=interrupted",
            d.name,
            interrupted_at,
        )
        reconciled.append(d.name)
    return reconciled
