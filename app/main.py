from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import (
    admin,
    agent,
    auth,
    media,
    observability,
    properties,
    public_agents,
    staff,
    tours,
)
from app.core.config import settings
from app.core.exceptions import register_exception_handlers
from app.core.logging import configure_logging
from app.core.observability import ObservabilityMiddleware
from app.services.maintenance import cleanup_loop

configure_logging()


@asynccontextmanager
async def lifespan(_: FastAPI):
    stop = asyncio.Event()
    task: asyncio.Task | None = None
    if settings.CLEANUP_ENABLED:
        task = asyncio.create_task(cleanup_loop(stop))
    try:
        yield
    finally:
        stop.set()
        if task is not None:
            await task


def create_app() -> FastAPI:
    app = FastAPI(
        title="Zent API",
        version="1.0.0",
        description="Zent Platform backend — Module 1: Identity & Access",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"],
        expose_headers=["X-Renewed-Token", "X-Request-ID"],
    )
    # added last -> outermost: times the whole stack, stamps X-Request-ID
    app.add_middleware(ObservabilityMiddleware)

    register_exception_handlers(app)
    app.include_router(auth.router, prefix=settings.API_PREFIX)
    app.include_router(properties.router, prefix=settings.API_PREFIX)
    app.include_router(media.router, prefix=settings.API_PREFIX)
    app.include_router(tours.router, prefix=settings.API_PREFIX)
    app.include_router(admin.router, prefix=settings.API_PREFIX)
    app.include_router(staff.router, prefix=settings.API_PREFIX)
    app.include_router(agent.router, prefix=settings.API_PREFIX)
    app.include_router(public_agents.router, prefix=settings.API_PREFIX)
    app.include_router(observability.router)  # no /api prefix, no auth

    if not settings.PROD:
        from app.api.routes import dev

        app.include_router(dev.router)

    @app.get("/health", tags=["meta"])
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
