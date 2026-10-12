"""State shared by routes and the error mapping (kept apart from app.py so routes can import it)."""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Request
from fastapi.responses import JSONResponse

from treechat.config import Config
from treechat.jobs.registry import JobRegistry
from treechat.jobs.summaries import SummaryJobs
from treechat.provider.base import Provider
from treechat.services.ctx import Ctx

# design.md, Error Handling.
STATUS = {
    "validation": 422,
    "not_found": 404,
    "conflict": 409,
    "busy": 409,
    "context_too_large": 422,
    "provider_unavailable": 503,
    "provider_error": 502,
    "refused": 502,
}


@dataclass(slots=True)
class State:
    """What routes need. Tests reach the provider here to script outcomes."""

    config: Config
    ctx: Ctx
    registry: JobRegistry
    provider: Provider
    summaries: SummaryJobs


def error_body(category: str, message: str, fields: tuple[str, ...] = ()) -> JSONResponse:
    return JSONResponse(
        status_code=STATUS[category], content={"error": category, "fields": list(fields), "message": message}
    )


def state_of(request: Request) -> State:
    return request.app.state.tc
