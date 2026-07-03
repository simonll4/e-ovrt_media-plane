"""Factory de la app FastAPI del servicio media-plane."""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from eovrt_media.service.routers import health
from eovrt_media.service.settings import ServiceSettings


@asynccontextmanager
async def _lifespan(app: FastAPI):
    # Task 11 agrega acá: carga de modelo, RunManager, GC y shutdown limpio.
    yield


def create_app(settings: ServiceSettings | None = None) -> FastAPI:
    settings = settings or ServiceSettings.from_env()
    app = FastAPI(title="eovrt-media-plane", lifespan=_lifespan)
    app.state.settings = settings
    app.state.ready = False
    app.state.load_error = None
    app.include_router(health.router)
    return app
