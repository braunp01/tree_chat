"""Sending and replies (Req 3, 4). One transaction per operation; the provider is called by jobs, not here."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from treechat.domain import context, render, rules
from treechat.domain.errors import Busy, Conflict
from treechat.domain.model import Manifest, Message, MessageId, Role, TreeId
from treechat.provider.base import ProviderResult
from treechat.services.ctx import Ctx
from treechat.services.trees import snapshot, tree_of_message
from treechat.store import repo
from treechat.store.codec import manifest_to_json

NO_TEXT = "(The model returned no text.)"


def send(ctx: Ctx, tree_id: TreeId, parent_id: MessageId, content: str) -> Message:
    """Req 3.1-3.2, 3.9: a new user Message as a child of the Current_Point, a reply of this Tree. Persisted before
    any model call; sending from a reply that already has children starts a new branch, with nothing else to do."""
    text = rules.clean_content(content)
    with ctx.store.transaction() as c:
        _, snap = snapshot(c, tree_id)
        rules.check_parent(snap, parent_id)
        m = Message(ctx.env.new_id(), tree_id, parent_id, Role.USER, text, created_at=ctx.env.now())
        repo.insert_message(c, m)
        repo.touch_tree(c, tree_id, m.created_at)
        return m


@dataclass(frozen=True, slots=True)
class PreparedReply:
    """Everything a reply job needs, decided before any model call."""

    user_message_id: MessageId
    tree_id: TreeId
    request: dict[str, Any]
    manifest: Manifest


def prepare_reply(ctx: Ctx, user_message_id: MessageId) -> PreparedReply:
    """Req 3.3, 3.7, 4.1: check a Reply can be requested and assemble exactly what the model will see."""
    with ctx.store.read() as c:
        tree_id = tree_of_message(c, user_message_id)
        _, snap = snapshot(c, tree_id)
    rules.check_can_reply(snap, user_message_id)
    if ctx.is_busy(user_message_id):
        raise Busy("The reply to this message is already being written.")
    manifest = context.assemble(snap, user_message_id, ctx.settings)
    return PreparedReply(user_message_id, tree_id, render.render(manifest, snap.messages), manifest)


def finish_reply(ctx: Ctx, prepared: PreparedReply, result: ProviderResult) -> Message:
    """Req 3.3, 4.4: persist the whole Reply with its manifest, only after the provider finished."""
    blocks_json = json.dumps(list(result.blocks), ensure_ascii=False, separators=(",", ":"))
    with ctx.store.transaction() as c:
        _, snap = snapshot(c, prepared.tree_id)
        if rules.reply_of(snap, prepared.user_message_id) is not None:
            raise Conflict("This message already has its reply.")
        m = Message(
            id=ctx.env.new_id(),
            tree_id=prepared.tree_id,
            parent_id=prepared.user_message_id,
            role=Role.ASSISTANT,
            content=result.text if result.text.strip() else NO_TEXT,
            blocks_json=blocks_json,
            model=result.model,
            stop_reason=result.stop_reason,
            created_at=ctx.env.now(),
        )
        repo.insert_message(c, m, manifest_to_json(prepared.manifest))
        repo.touch_tree(c, prepared.tree_id, m.created_at)
        return m
