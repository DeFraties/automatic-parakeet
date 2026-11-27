"""FastAPI application entry point."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import daily, games, health, leaderboards, meta, removals, telemetry
from app.core.config import get_settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    from app.core.photo_checker import start_background_checker

    checker = start_background_checker()
    yield
    if checker:
        checker.stop()


def _setup_logging() -> None:
    """Show the app's own INFO messages (e.g. photo-check progress) next to Uvicorn's logs."""
    app_log = logging.getLogger("app")
    if not app_log.handlers:
        h = logging.StreamHandler()
        h.setFormatter(logging.Formatter("%(levelname)s:     %(message)s"))
        app_log.addHandler(h)
        app_log.setLevel(logging.INFO)
        app_log.propagate = False


def create_app() -> FastAPI:
    _setup_logging()
    s = get_settings()
    app = FastAPI(
        lifespan=lifespan,
        title="Ballpark API",
        version="0.1.0",
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=s.cors_origin_list,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type", "X-Device-Id"],
    )
    for r in (
        health.router,
        meta.router,
        games.router,
        daily.router,
        leaderboards.router,
        removals.router,
        telemetry.router,
    ):
        app.include_router(r, prefix="/api")
    return app


app = create_app()
