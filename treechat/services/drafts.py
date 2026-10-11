"""Reads and writes around generated text. The model calls themselves live in jobs/ (Req 11, 12.1)."""

from __future__ import annotations

from dataclasses import dataclass

from treechat.domain import rules
from treechat.domain.model import BranchId, BranchKind, Role
from treechat.services.ctx import Ctx
from treechat.services.trees import snapshot_of_branch
from treechat.store import repo


@dataclass(frozen=True, slots=True)
class DraftSource:
    intent: str | None
    anchor_quote: str
    anchor_message: str
    messages: list[tuple[Role, str]]  # the Branch's own Messages, in order


def draft_source(ctx: Ctx, branch_id: BranchId) -> DraftSource | None:
    """What the generators may read: only a Tangent's Anchor, Intent and own Messages (Req 11.1-11.2, 12.1)."""
    with ctx.store.read() as c:
        snap = snapshot_of_branch(c, branch_id)
    b = rules.branch(snap, branch_id)
    if b.kind is not BranchKind.TANGENT or b.anchor is None:
        return None
    return DraftSource(
        b.intent,
        b.anchor.quoted_text,
        snap.messages[b.anchor.message_id].content,
        [(snap.messages[m].role, snap.messages[m].content) for m in snap.chain(branch_id)],
    )


def store_generated(ctx: Ctx, branch_id: BranchId, kind: str, text: str, model: str) -> None:
    with ctx.store.transaction() as c:
        repo.insert_generated(c, ctx.env.new_id(), branch_id, kind, text, model, ctx.env.now())
