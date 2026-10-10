"""Turn a Manifest into the exact provider request (Req 7.4-7.5). Byte-deterministic: nothing volatile."""

from __future__ import annotations

import copy
import json
from collections.abc import Mapping
from typing import Any

from treechat.domain.context import SYSTEM_PROMPT_VERSION
from treechat.domain.model import FramingEntry, Manifest, Message, MessageId, Role

# Frozen. Changing this text changes every request prefix: bump SYSTEM_PROMPT_VERSION with it.
SYSTEM_PROMPT_V1 = (
    "You are the assistant in Tree Chat, a chat app where a conversation can branch into tangents.\n"
    "Two kinds of text in user turns come from the app, not from the user:\n"
    "- <tree_chat_framing> follows the first message of a tangent. It quotes the passage the tangent is about and "
    "the user's intent. Follow its instruction to stay on the tangent.\n"
    "- <tree_chat_note> carries the conclusion of a tangent that was closed and merged back here. Treat it "
    "as established context the user has accepted, not as something they just said."
)
SYSTEM_PROMPTS = {1: SYSTEM_PROMPT_V1}
assert SYSTEM_PROMPT_VERSION in SYSTEM_PROMPTS

_EPHEMERAL = {"type": "ephemeral"}

type Block = dict[str, Any]
type Turn = dict[str, Any]


def _blocks_for(entry_message: Message) -> tuple[str, list[Block]]:
    if entry_message.role is Role.ASSISTANT:
        if entry_message.blocks_json:
            blocks: list[Block] = json.loads(entry_message.blocks_json)
            return "assistant", blocks
        return "assistant", [{"type": "text", "text": entry_message.content}]
    # User Messages and Notes are both user-role text; Notes are labelled by their own tags (Req 7.9).
    return "user", [{"type": "text", "text": entry_message.content}]


def _mark_cache(blocks: list[Block]) -> bool:
    """Put the breakpoint on the last block that may carry one (not a thinking block)."""
    for block in reversed(blocks):
        if block.get("type") not in ("thinking", "redacted_thinking"):
            block["cache_control"] = dict(_EPHEMERAL)
            return True
    return False


def render(manifest: Manifest, messages: Mapping[MessageId, Message]) -> dict[str, Any]:
    """The request parameters for the provider, excluding transport options (stream, betas, fallbacks).

    Adjacent user-role entries (a user Message, Notes) merge into one user turn, in order. A Framing_Block is a
    mid-conversation `system` message, which always follows a user turn and precedes an assistant turn or ends the
    list. Stored assistant blocks, including signed thinking, are replayed unchanged: a Branch's Context only grows,
    so every replayed block still sits on the prefix that produced it (design.md, Thinking blocks).
    """
    turns: list[Turn] = []
    entry_blocks: list[list[Block] | None] = []  # per entry: its own blocks (shared with `turns`), None for framing
    for entry in manifest.entries:
        if isinstance(entry, FramingEntry):
            turns.append({"role": "system", "content": entry.text})
            entry_blocks.append(None)
            continue
        role, blocks = _blocks_for(messages[entry.id])
        blocks = copy.deepcopy(blocks)
        entry_blocks.append(blocks)
        if turns and turns[-1]["role"] == role:
            turns[-1]["content"].extend(blocks)
        else:
            turns.append({"role": role, "content": list(blocks)})  # a copy: later entries extend this list
    # Breakpoint 1 sits on the last block of the Inherited_Prefix itself, even when that block shares a turn with
    # the Branch's own first Message. A system message cannot carry it, so step back to the nearest Message entry.
    bp = manifest.cache_breakpoint_after
    while bp is not None and bp >= 0 and entry_blocks[bp] is None:
        bp -= 1
    if bp is not None and bp >= 0:
        _mark_cache(entry_blocks[bp] or [])
    return {
        "model": manifest.model,
        "max_tokens": manifest.max_tokens,
        "system": [{"type": "text", "text": SYSTEM_PROMPTS[manifest.system_prompt_version]}],
        "messages": turns,
        "thinking": {"type": "adaptive"},
        "output_config": {"effort": manifest.effort},
        # Breakpoint 2: automatic caching of the growing tail (design.md, Prompt caching).
        "cache_control": dict(_EPHEMERAL),
    }


def request_bytes(request: Mapping[str, Any]) -> bytes:
    """Canonical serialisation used by tests and by the Fake provider."""
    return json.dumps(request, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
