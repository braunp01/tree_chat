"""The only code that calls the provider (design.md, Architecture).

A Reply persists only after the provider finishes; a failure persists nothing and keeps the user Message (Req 3.5).
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from treechat.domain.errors import DomainError
from treechat.provider.base import ErrorCategory, Provider, ProviderError
from treechat.services.ctx import Ctx
from treechat.services.messages import PreparedReply, finish_reply
from treechat.services.views import message_out

log = logging.getLogger("treechat.jobs")

type Emit = Callable[[dict[str, Any]], None]


async def run_reply(ctx: Ctx, provider: Provider, prepared: PreparedReply, emit: Emit) -> None:
    """Stream one reply and persist it. Never raises: every outcome is an event (Req 3.3-3.8)."""

    async def on_delta(text: str) -> None:
        emit({"type": "delta", "text": text})

    try:
        result = await provider.generate(prepared.request, on_delta)
    except ProviderError as exc:
        emit({"type": "error", "error": exc.category.value, "message": exc.message})
        return
    except Exception:  # a bug or an SDK surprise must still end the stream cleanly
        log.exception("reply job failed")
        emit({"type": "error", "error": ErrorCategory.PROVIDER_ERROR.value, "message": "The reply failed."})
        return
    try:
        message = finish_reply(ctx, prepared, result)
    except DomainError as exc:
        emit({"type": "error", "error": exc.category, "message": exc.message})
        return
    except Exception:
        log.exception("could not save the reply")
        emit({"type": "error", "error": ErrorCategory.PROVIDER_ERROR.value, "message": "The reply could not be saved."})
        return
    emit({"type": "done", "message": message_out(message)})
