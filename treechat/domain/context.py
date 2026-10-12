"""What the model sees for a Reply: the Path to its user Message, and nothing else (Req 4.1). Pure."""

from __future__ import annotations

from treechat.domain import rules
from treechat.domain.model import Manifest, MessageEntry, MessageId, Settings, TreeSnapshot

SYSTEM_PROMPT_VERSION = 2


def assemble(snap: TreeSnapshot, user_message_id: MessageId, settings: Settings) -> Manifest:
    """Req 4.1, 4.4. The cache breakpoint sits on the last Message before the new user Message, so every Reply's
    request is a byte-identical extension of its parent Reply's request (Req 4.3)."""
    ids = rules.path(snap, user_message_id)
    entries = tuple(MessageEntry(i, snap.messages[i].role) for i in ids)
    return Manifest(
        entries=entries,
        model=settings.model,
        effort=settings.effort,
        max_tokens=settings.max_tokens,
        system_prompt_version=SYSTEM_PROMPT_VERSION,
        cache_breakpoint_after=len(entries) - 2 if len(entries) >= 2 else None,
    )
