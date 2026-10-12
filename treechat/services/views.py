"""Read models: the JSON the Front_End draws from (design.md, API Contract). One read transaction each."""

from __future__ import annotations

import json
from typing import Any

from treechat.domain import rules
from treechat.domain.errors import NotFound
from treechat.domain.model import Message, MessageId, Role, TreeId
from treechat.services.ctx import Ctx
from treechat.services.trees import snapshot, tree_of_message
from treechat.store import repo
from treechat.store.codec import manifest_to_json

LABEL = 60


def tree_row_out(t: repo.TreeRow) -> dict[str, Any]:
    return {"id": t.id, "title": t.title, "created_at": t.created_at, "last_activity_at": t.last_activity_at}


def message_out(m: Message) -> dict[str, Any]:
    """The JSON shape of a Message in API responses and `done` events."""
    return {
        "id": m.id,
        "tree_id": m.tree_id,
        "parent_id": m.parent_id,
        "role": m.role.value,
        "content": m.content,
        "model": m.model,
        "stop_reason": m.stop_reason,
        "cut_off": m.stop_reason == "max_tokens",  # Req 3.6
        "created_at": m.created_at,
    }


def list_trees(ctx: Ctx) -> list[dict[str, Any]]:
    """Req 1.2."""
    with ctx.store.read() as c:
        return [tree_row_out(t) for t in repo.list_trees(c)]


def tree_out(ctx: Ctx, tree_id: TreeId) -> dict[str, Any]:
    """Req 2.2, 6: the Tree's shape without Message text, its derived Branches and its default Current_Point."""
    with ctx.store.read() as c:
        tree, snap = snapshot(c, tree_id)
    branches = rules.branches(snap)
    return {
        **tree_row_out(tree),
        "default_point": rules.default_point(snap),
        "branches": [
            {
                "id": b.id,
                "parent_branch_id": b.parent_branch_id,
                "message_ids": list(b.message_ids),
                "label": rules.title_from_root(snap.messages[b.id].content)[:LABEL],  # Req 6.2
                "forked_from": snap.messages[b.id].parent_id,  # Req 6.8
                "forked_from_preview": rules.title_from_root(snap.messages[p].content)
                if (p := snap.messages[b.id].parent_id)
                else None,
                "created_at": snap.messages[b.id].created_at,
            }
            for b in branches
        ],
    }


def path_out(ctx: Ctx, message_id: MessageId) -> dict[str, Any]:
    """Req 2.1, 2.4, 3.10: the Path to a Message with full text, and for each Message how many children it has."""
    with ctx.store.read() as c:
        _, snap = snapshot(c, tree_of_message(c, message_id))
    ids = rules.path(snap, message_id)
    out = [{**message_out(snap.messages[i]), "child_count": len(snap.kids(i))} for i in ids]
    last = snap.messages[ids[-1]]
    waiting = last.role is Role.USER and rules.reply_of(snap, last.id) is None
    return {
        "tree_id": last.tree_id,
        "messages": out,
        "awaiting_reply": waiting,
        "reply_in_progress": waiting and ctx.is_busy(last.id),
        "latest_below": rules.latest_reply_below(snap, last.id),  # Req 2.4: "jump to the latest"
    }


def manifest_out(ctx: Ctx, message_id: MessageId) -> dict[str, Any]:
    """Req 4.5: the Context_Manifest of a Reply, exactly as stored."""
    with ctx.store.read() as c:
        tree_of_message(c, message_id)
        m = repo.get_manifest(c, message_id)
    if m is None:
        raise NotFound(f"Message {message_id} has no manifest; only replies do.")
    return json.loads(manifest_to_json(m))
