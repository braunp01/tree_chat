"""FastAPI application factory. HTTP shapes only; no business rules (design.md, Layered Responsibilities)."""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from treechat.config import Config, ProviderKind, load_config

WEB_DIST = Path(__file__).resolve().parents[2] / "web" / "dist"


def create_app(config: Config | None = None) -> FastAPI:
    cfg = config or load_config()
    app = FastAPI(title="Tree Chat")

    @app.get("/api/health")
    def health() -> dict[str, object]:  # pyright: ignore[reportUnusedFunction]
        # Req 17.3: report whether credentials exist, never their value.
        has_credentials = cfg.provider is ProviderKind.FAKE or bool(os.environ.get("ANTHROPIC_API_KEY"))
        return {"ok": True, "provider": cfg.provider.value, "credentials": has_credentials}

    if WEB_DIST.is_dir():
        app.mount("/", StaticFiles(directory=WEB_DIST, html=True), name="web")
    return app
