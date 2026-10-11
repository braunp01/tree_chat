"""Sending Messages, replies, edits and regenerations (Req 2, 3)."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from typing import Any

from treechat.domain import context, render, rules
from treechat.domain.context import framing_text
from treechat.domain.errors import Busy, Conflict
from treechat.domain.model import (
    Action,
    Anchor,
    Branch,
    BranchId,
    BranchKind,
    Manifest,
    Message,
    MessageId,
    Role,
    Status,
    TreeId,
    TreeSnapshot,
)
from treechat.provider.base import ProviderResult
from treechat.services.ctx import Ctx
from treechat.services.trees import snapshot_of_branch, tree_of_message
from treechat.store import repo
from treechat.store.codec import manifest_to_json

NO_TEXT = "(The model returned no text.)"


def _append(
    ctx: Ctx,
    c: sqlite3.Connection,
    snap: TreeSnapshot,
    b: Branch,
    role: Role,
    content: str,
    *,
    source_branch_id: BranchId | None = None,
    blocks_json: str | None = None,
    model: str | None = None,
    stop_reason: str | None = None,
    manifest_json: str | None = None,
) -> Message:
    """Add one Message at the Tip of `b` inside the caller's transaction."""
    chain = snap.chain(b.id)
    now = ctx.env.now()
    m = Message(
        id=ctx.env.new_id(),
        branch_id=b.id,
        parent_message_id=rules.tip(snap, b.id),
        seq=len(chain),
        role=role,
        content=content,
        blocks_json=blocks_json,
        model=model,
        stop_reason=stop_reason,
        source_branch_id=source_branch_id,
        created_at=now,
    )
    if not chain and b.kind is BranchKind.TANGENT and b.anchor is not None:
        # Req 7.3: the Framing_Block is fixed when the Branch receives its first Message.
        repo.set_framing(c, b.id, framing_text(b.anchor.quoted_text, b.intent))
    repo.insert_message(c, b.tree_id, m, manifest_json)
    repo.touch_tree(c, b.tree_id, now)
    return m


def send_message(ctx: Ctx, branch_id: BranchId, content: str) -> Message:
    """Req 2.1, 2.5, 2.7-2.9."""
    text = rules.clean_content(content)
    with ctx.store.transaction() as c:
        snap = snapshot_of_branch(c, branch_id)
        b = rules.branch(snap, branch_id)
        if ctx.is_busy(branch_id):
            raise Busy("A reply is already being generated in this branch.")
        new_status = rules.transition(b.status, Action.SEND, b.kind)  # a closed Branch refuses (Req 12.8)
        chain = snap.chain(branch_id)
        if chain and snap.messages[chain[-1]].role is Role.USER:
            raise Conflict("Wait for the reply to your last message, or request it again, before sending another.")
        if not chain and b.kind is BranchKind.ALTERNATIVE:
            raise Conflict("Request the reply for this alternative before sending another message.")
        m = _append(ctx, c, snap, b, Role.USER, text)
        if new_status is not b.status:
            repo.set_status(c, branch_id, new_status, m.created_at)  # Req 2.8: sending resumes a parked Branch
        tree = repo.get_tree(c, b.tree_id)
        if tree is not None and tree.title is None:
            repo.set_title(c, b.tree_id, text.strip()[:60].strip())  # Req 1.3
        return m


@dataclass(frozen=True, slots=True)
class PreparedReply:
    """Everything a reply job needs, decided before any model call."""

    branch_id: BranchId
    tree_id: TreeId
    chain_len: int
    request: dict[str, Any]
    manifest: Manifest


def prepare_reply(ctx: Ctx, branch_id: BranchId) -> PreparedReply:
    """Req 2.2, 2.5, 7.1: check a reply can be requested and assemble exactly what the model will see."""
    with ctx.store.read() as c:
        snap = snapshot_of_branch(c, branch_id)
    b = rules.branch(snap, branch_id)
    if b.status is Status.CLOSED:
        raise Conflict("This branch is closed.")
    if ctx.is_busy(branch_id):
        raise Busy("A reply is already being generated in this branch.")
    chain = snap.chain(branch_id)
    if not chain and b.kind is not BranchKind.ALTERNATIVE:
        raise Conflict("There is nothing to reply to yet.")
    tip_id = rules.tip(snap, branch_id)
    if tip_id is None or snap.messages[tip_id].role is not Role.USER:
        raise Conflict("There is nothing to reply to: the last message is not yours.")
    manifest = context.assemble(snap, branch_id, ctx.settings)
    return PreparedReply(branch_id, b.tree_id, len(chain), render.render(manifest, snap.messages), manifest)


def finish_reply(ctx: Ctx, prepared: PreparedReply, result: ProviderResult) -> Message:
    """Req 2.2, 7.7: persist the whole reply with its manifest, only after the provider finished."""
    blocks_json = json.dumps(list(result.blocks), ensure_ascii=False, separators=(",", ":"))
    with ctx.store.transaction() as c:
        snap = snapshot_of_branch(c, prepared.branch_id)
        b = rules.branch(snap, prepared.branch_id)
        if b.status is Status.CLOSED or len(snap.chain(prepared.branch_id)) != prepared.chain_len:
            raise Conflict("The branch changed while the reply was being written.")
        return _append(
            ctx,
            c,
            snap,
            b,
            Role.ASSISTANT,
            result.text.strip() and result.text or NO_TEXT,
            blocks_json=blocks_json,
            model=result.model,
            stop_reason=result.stop_reason,
            manifest_json=manifest_to_json(prepared.manifest),
        )


def _new_alternative(ctx: Ctx, c: sqlite3.Connection, m: Message, tree_id: TreeId) -> Branch:
    """Req 3.2-3.3: whole-Message Anchor, Fork_Point = the predecessor, parent = the Message's Branch."""
    now = ctx.env.now()
    alt = Branch(
        id=ctx.env.new_id(),
        tree_id=tree_id,
        parent_branch_id=m.branch_id,
        kind=BranchKind.ALTERNATIVE,
        anchor=Anchor(m.id, 0, len(m.content), m.content),
        fork_point_message_id=m.parent_message_id,
        intent=None,
        status=Status.OPEN,
        framing_text=None,
        created_at=now,
        status_since=now,
    )
    repo.insert_branch(c, alt)
    repo.touch_tree(c, tree_id, now)
    return alt


def edit_message(ctx: Ctx, message_id: MessageId, content: str) -> Branch:
    """Req 3.2: editing a user Message creates an Alternative whose first Message is the edited text."""
    text = rules.clean_content(content)
    with ctx.store.transaction() as c:
        tree_id = tree_of_message(c, message_id)
        snap = repo.load_snapshot(c, tree_id)
        m = snap.messages[message_id]
        if m.role is not Role.USER:
            raise Conflict("Only your own messages can be edited.")
        alt = _new_alternative(ctx, c, m, tree_id)
        snap = repo.load_snapshot(c, tree_id)
        _append(ctx, c, snap, snap.branches[alt.id], Role.USER, text)
        return alt


def regenerate_message(ctx: Ctx, message_id: MessageId) -> Branch:
    """Req 3.3: an empty Alternative; the caller then requests its reply."""
    with ctx.store.transaction() as c:
        tree_id = tree_of_message(c, message_id)
        snap = repo.load_snapshot(c, tree_id)
        m = snap.messages[message_id]
        if m.role is not Role.ASSISTANT:
            raise Conflict("Only a reply can be regenerated.")
        return _new_alternative(ctx, c, m, tree_id)
