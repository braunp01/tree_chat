"""The only code that calls the provider for work the user sees (design.md, Layered Responsibilities).

A reply persists only after the provider finishes; a failure persists nothing and keeps the user Message (Req 2.3).
Generated text (Req 11) fails quietly and never blocks anything (Req 11.3); it is never placed in a Context (Req 11.5).
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from treechat.domain import prompts
from treechat.domain.errors import DomainError
from treechat.domain.model import BranchId, Message
from treechat.provider.base import ErrorCategory, Provider, ProviderError
from treechat.services import drafts
from treechat.services.ctx import Ctx
from treechat.services.messages import PreparedReply, finish_reply

log = logging.getLogger("treechat.jobs")

type Emit = Callable[[dict[str, Any]], None]


def message_out(m: Message) -> dict[str, Any]:
    """The JSON shape of a Message in API responses and `done` events."""
    return {
        "id": m.id,
        "branch_id": m.branch_id,
        "parent_message_id": m.parent_message_id,
        "seq": m.seq,
        "role": m.role.value,
        "content": m.content,
        "model": m.model,
        "stop_reason": m.stop_reason,
        "cut_off": m.stop_reason == "max_tokens",
        "source_branch_id": m.source_branch_id,
        "created_at": m.created_at,
    }


async def run_reply(ctx: Ctx, provider: Provider, prepared: PreparedReply, emit: Emit) -> None:
    """Stream one reply and persist it. Never raises: every outcome is an event (Req 2.2-2.4, 2.6)."""

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


async def generate_intent(ctx: Ctx, provider: Provider, branch_id: BranchId) -> str | None:
    """Req 11.1: a one-line Generated_Intent from the Anchor and its Message only."""
    src = drafts.draft_source(ctx, branch_id)
    if src is None or src.intent:
        return None
    try:
        system, prompt = prompts.intent_prompt(src.anchor_quote, src.anchor_message)
        text = prompts.one_line(await provider.complete(system, prompt, 300), prompts.INTENT_MAX)
        if text:
            drafts.store_generated(ctx, branch_id, "intent", text, ctx.settings.model)
        return text or None
    except (ProviderError, DomainError) as exc:
        log.info("generated intent skipped: %s", exc)  # Req 11.3: the Anchor quote is shown instead
        return None


async def generate_standing(ctx: Ctx, provider: Provider, branch_id: BranchId) -> str | None:
    """Req 11.2: where a parked Tangent that has replies stands."""
    src = drafts.draft_source(ctx, branch_id)
    if src is None or not any(role.value == "assistant" for role, _ in src.messages):
        return None
    try:
        system, prompt = prompts.standing_prompt(src.intent, src.anchor_quote, src.messages)
        text = prompts.one_line(await provider.complete(system, prompt, 300), prompts.INTENT_MAX)
        if text:
            drafts.store_generated(ctx, branch_id, "standing", text, ctx.settings.model)
        return text or None
    except (ProviderError, DomainError) as exc:
        log.info("standing summary skipped: %s", exc)
        return None


async def draft_conclusion(ctx: Ctx, provider: Provider, branch_id: BranchId) -> str:
    """Req 12.1: a draft Conclusion for the close panel. Not stored; failures reach the caller."""
    src = drafts.draft_source(ctx, branch_id)
    if src is None:
        return ""
    system, prompt = prompts.conclusion_prompt(src.intent, src.anchor_quote, src.messages)
    return (await provider.complete(system, prompt, 800)).strip()[:1500]
