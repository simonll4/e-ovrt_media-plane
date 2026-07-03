"""Retención de RUNS_DIR: GC por antigüedad y tamaño total (Spec A §7.4)."""
from __future__ import annotations

import shutil
import time
from pathlib import Path

from eovrt_media.service.settings import ServiceSettings


def _dir_size_bytes(path: Path) -> int:
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file())


def gc_runs_dir(settings: ServiceSettings) -> list[str]:
    runs_dir = settings.runs_dir
    if not runs_dir.is_dir():
        return []
    removed: list[str] = []
    dirs = sorted(
        (d for d in runs_dir.iterdir() if d.is_dir()), key=lambda d: d.stat().st_mtime
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
