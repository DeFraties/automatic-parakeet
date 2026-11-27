"""FastAPI application entry point."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import daily, games, health, leaderboards, meta, removals, telemetry
from app.core.config import get_settings


def create_app() -> FastAPI:
    s = get_settings()
    app = FastAPI(
        title="Ballpark API", version="0.1.0", docs_url="/api/docs", openapi_url="/api/openapi.json"
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
