"""Factory de la app FastAPI del servicio media-plane."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from starlette.concurrency import run_in_threadpool

from eovrt_media.service.retention import gc_runs_dir
from eovrt_media.service.routers import catalog, health, model, runs, stream
from eovrt_media.service.settings import ServiceSettings

logger = logging.getLogger(__name__)


@asynccontextmanager
async def _lifespan(app: FastAPI):
    settings: ServiceSettings = app.state.settings
    adapter = None
    try:
        from eovrt_media.config.loader import resolve_model_ref
        from eovrt_media.models import create_adapter
        from eovrt_media.service.run_manager import RunManager

        model_section = resolve_model_ref(settings.model_ref, settings.catalog_root)
        if settings.model_device:
            model_section.device = settings.model_device
        adapter = create_adapter(model_section)
        await run_in_threadpool(adapter.load)  # carga (y warmup) UNA vez
        app.state.model_section = model_section
        app.state.adapter = adapter
        app.state.manager = RunManager(adapter, model_section, settings)
        app.state.ready = True
        logger.info("Modelo %s cargado (device=%s)", settings.model_ref, model_section.device)
    except Exception as exc:  # noqa: BLE001 — /readyz reporta la causa; sin recarga (Spec A §8)
        app.state.load_error = str(exc)
        logger.exception("Fallo de carga del modelo %s", settings.model_ref)
    removed = gc_runs_dir(settings)
    if removed:
        logger.info("GC de retención: %d runs eliminados", len(removed))
    yield
    # SIGTERM/shutdown = camino stop (Spec A §4): el redeploy es el caso normal
    manager = getattr(app.state, "manager", None)
    if manager is not None:
        manager.stop_active(cause="shutdown")
        manager.join_active(timeout=settings.shutdown_grace_seconds)
        manager.shutdown()
    if adapter is not None:
        adapter.close()


def create_app(settings: ServiceSettings | None = None) -> FastAPI:
    settings = settings or ServiceSettings.from_env()
    app = FastAPI(title="eovrt-media-plane", lifespan=_lifespan)
    app.state.settings = settings
    app.state.ready = False
    app.state.load_error = None
    app.include_router(health.router)
    app.include_router(model.router)
    app.include_router(runs.router)
    app.include_router(stream.router)
    app.include_router(catalog.router)
    return app
