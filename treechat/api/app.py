"""FastAPI application factory. HTTP shapes only; no business rules (design.md, Layered Responsibilities)."""

from __future__ import annotations

import os
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from treechat.api.routes import router
from treechat.api.state import State, error_body
from treechat.config import Config, ProviderKind, load_config
from treechat.domain.errors import DomainError
from treechat.domain.model import Settings
from treechat.env import system_env
from treechat.jobs.registry import JobRegistry
from treechat.jobs.summaries import SummaryJobs
from treechat.provider import make_provider
from treechat.provider.base import ProviderError
from treechat.services.ctx import Ctx
from treechat.store.db import Store

WEB_DIST = Path(__file__).resolve().parents[2] / "web" / "dist"


def create_app(config: Config | None = None) -> FastAPI:
    cfg = config or load_config()
    registry = JobRegistry()
    ctx = Ctx(Store(cfg.db_path), system_env(), Settings(cfg.model, cfg.effort), registry.is_busy)
    provider = make_provider(cfg)
    state = State(cfg, ctx, registry, provider, SummaryJobs(ctx, provider, registry))

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncGenerator[None]:
        yield
        await registry.drain()  # let replies in progress finish before the process ends (Req 3.8)

    app = FastAPI(title="Tree Chat", lifespan=lifespan)
    app.state.tc = state

    @app.exception_handler(DomainError)
    async def _domain(_: Request, exc: DomainError) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        return error_body(exc.category, exc.message, exc.fields)

    @app.exception_handler(ProviderError)
    async def _provider(_: Request, exc: ProviderError) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        return error_body(exc.category.value, exc.message)

    @app.exception_handler(RequestValidationError)
    async def _request(_: Request, exc: RequestValidationError) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        """Malformed bodies use the same shape and name the offending field (Req 3.9)."""
        fields: list[str] = []
        first: dict[str, Any] = exc.errors()[0] if exc.errors() else {}
        loc = [str(p) for p in first.get("loc", ()) if p != "body"]
        if loc:
            fields.append(loc[0])
        return error_body("validation", str(first.get("msg", "Invalid request.")), tuple(fields))

    @app.get("/api/health")
    def health() -> dict[str, object]:  # pyright: ignore[reportUnusedFunction]
        # Req 8.3: report whether credentials exist, never their value.
        has_credentials = cfg.provider is ProviderKind.FAKE or bool(os.environ.get("ANTHROPIC_API_KEY"))
        return {"ok": True, "provider": cfg.provider.value, "credentials": has_credentials}

    app.include_router(router)

    if WEB_DIST.is_dir():
        app.mount("/", StaticFiles(directory=WEB_DIST, html=True), name="web")
    return app
