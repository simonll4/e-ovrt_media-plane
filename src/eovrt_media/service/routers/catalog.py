"""Catálogos del servicio: plugins de ingesta y datasets (Spec A §3.1)."""
from __future__ import annotations

import logging
from pathlib import Path

import yaml
from fastapi import APIRouter, Request

from eovrt_media.config.loader import find_plane_catalog_root, rebase_dataset_path
from eovrt_media.sources.registry import list_plugins

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/catalog")


@router.get("/ingest-plugins")
def ingest_plugins() -> list[dict]:
    return list_plugins()


@router.get("/datasets")
def datasets(request: Request) -> list[dict]:
    settings = request.app.state.settings
    plane_root = find_plane_catalog_root(None, settings.catalog_root)
    datasets_dir = plane_root / "datasets"
    entries: list[dict] = []
    if datasets_dir.is_dir():
        for yaml_path in sorted(datasets_dir.glob("*.yaml")):
            try:
                data = yaml.safe_load(yaml_path.read_text()) or {}
            except (yaml.YAMLError, OSError):
                logger.warning("Dataset catalog entry ilegible, se omite: %s", yaml_path, exc_info=True)
                continue
            raw_path = data.get("path", "")
            resolved = rebase_dataset_path(raw_path, settings.datasets_root)
            entries.append(
                {
                    "id": yaml_path.stem,
                    "description": data.get("description"),
                    "path": resolved,
                    "available": Path(resolved).exists() if resolved else False,
                }
            )
    return entries
