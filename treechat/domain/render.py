"""Turn a Manifest into the exact provider request (Req 4.2-4.3). Byte-deterministic: nothing volatile."""

from __future__ import annotations

import copy
import json
from collections.abc import Mapping
from typing import Any

from treechat.domain.context import SYSTEM_PROMPT_VERSION
from treechat.domain.model import Manifest, Message, MessageId, Role

# Frozen. Changing this text changes every request prefix: add a new version instead (Req 4.2).
SYSTEM_PROMPT_V2 = (
    "You are the assistant in Tree Chat, a chat app in which the user can go back to any earlier point of a "
    "conversation and continue differently from there. The messages you receive are the complete conversation "
    "along the current path; you do not see other branches."
)
SYSTEM_PROMPTS = {2: SYSTEM_PROMPT_V2}
assert SYSTEM_PROMPT_VERSION in SYSTEM_PROMPTS

_EPHEMERAL = {"type": "ephemeral"}

type Block = dict[str, Any]
type Turn = dict[str, Any]


def _blocks_for(m: Message, request_model: str) -> list[Block]:
    if m.role is Role.ASSISTANT:
        if m.blocks_json:
            blocks: list[Block] = json.loads(m.blocks_json)
            if m.model is not None and m.model != request_model:
                # Written by another model (a refusal fallback served it): its thinking is bound to that model and
                # is not replayed here; the visible text still is (design.md, Thinking replay).
                blocks = [b for b in blocks if b.get("type") not in ("thinking", "redacted_thinking")]
            return blocks
        return [{"type": "text", "text": m.content}]
    return [{"type": "text", "text": m.content}]


def _mark_cache(blocks: list[Block]) -> None:
    """Put the breakpoint on the last block that may carry one (not a thinking block)."""
    for block in reversed(blocks):
        if block.get("type") not in ("thinking", "redacted_thinking"):
            block["cache_control"] = dict(_EPHEMERAL)
            return


def render(manifest: Manifest, messages: Mapping[MessageId, Message]) -> dict[str, Any]:
    """The request parameters for the provider, excluding transport options (stream, betas, fallbacks).

    Roles alternate along a Path (Req 5.3), so each Message is one turn. Stored assistant blocks, including signed
    thinking, are replayed unchanged: a Reply's Path never changes, so every replayed block still sits on the prefix
    that produced it (Req 4.2, design.md Thinking replay).
    """
    turns: list[Turn] = []
    for i, entry in enumerate(manifest.entries):
        m = messages[entry.id]
        blocks = copy.deepcopy(_blocks_for(m, manifest.model))
        if i == manifest.cache_breakpoint_after:
            _mark_cache(blocks)
        turns.append({"role": "assistant" if m.role is Role.ASSISTANT else "user", "content": blocks})
    return {
        "model": manifest.model,
        "max_tokens": manifest.max_tokens,
        "system": [{"type": "text", "text": SYSTEM_PROMPTS[manifest.system_prompt_version]}],
        "messages": turns,
        "thinking": {"type": "adaptive"},
        "output_config": {"effort": manifest.effort},
        # Automatic caching of the growing tail (design.md, Prompt caching).
        "cache_control": dict(_EPHEMERAL),
    }


def request_bytes(request: Mapping[str, Any]) -> bytes:
    """Canonical serialisation used by tests and by the Fake provider."""
    return json.dumps(request, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
