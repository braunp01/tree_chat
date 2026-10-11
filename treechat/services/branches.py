"""Spawning Tangents and moving Branches between Statuses (Req 4, 9, 10, 12.7)."""

from __future__ import annotations

from treechat.domain import rules
from treechat.domain.errors import Conflict, ValidationError
from treechat.domain.model import Action, Anchor, Branch, BranchId, BranchKind, MessageId, Status
from treechat.services.ctx import Ctx
from treechat.services.trees import snapshot_of_branch, tree_of_message
from treechat.store import repo


def _fork_point_for(fork_at: str, anchor_message: MessageId, parent_tip: MessageId | None) -> MessageId | None:
    if fork_at == "anchor":
        return anchor_message
    if fork_at == "tip":
        return parent_tip
    raise ValidationError("fork_point", "fork_at must be 'anchor' or 'tip'.")


def spawn_tangent(
    ctx: Ctx,
    message_id: MessageId,
    start: int,
    end: int,
    quoted_text: str,
    intent: str | None = None,
    fork_at: str = "anchor",
    status: Status = Status.PARKED,
) -> Branch:
    """Req 4.2-4.8: the parent is the Branch that owns the Anchor's Message, wherever the user was looking."""
    clean_intent = rules.clean_intent(intent)
    if status not in (Status.PARKED, Status.OPEN):
        raise ValidationError("status", "A new tangent is parked or open.")
    if fork_at not in ("anchor", "tip"):
        raise ValidationError("fork_point", "fork_at must be 'anchor' or 'tip'.")
    with ctx.store.transaction() as c:
        tree_id = tree_of_message(c, message_id)
        snap = repo.load_snapshot(c, tree_id)
        m = snap.messages[message_id]
        problem = rules.anchor_error(m.content, start, end, quoted_text)
        if problem:
            raise ValidationError("anchor", problem)
        now = ctx.env.now()
        b = Branch(
            id=ctx.env.new_id(),
            tree_id=tree_id,
            parent_branch_id=m.branch_id,
            kind=BranchKind.TANGENT,
            anchor=Anchor(message_id, start, end, quoted_text),
            fork_point_message_id=_fork_point_for(fork_at, message_id, rules.tip(snap, m.branch_id)),
            intent=clean_intent,
            status=status,
            framing_text=None,
            created_at=now,
            status_since=now,
        )
        repo.insert_branch(c, b)
        repo.touch_tree(c, tree_id, now)
        return b


def change_status(ctx: Ctx, branch_id: BranchId, action: Action) -> Branch:
    """Park, resume and reopen (Req 10.1, 12.7). Closing has its own operation (services.closing)."""
    if action not in (Action.PARK, Action.RESUME, Action.REOPEN):
        raise ValueError(f"{action} is not a plain status change")
    with ctx.store.transaction() as c:
        snap = snapshot_of_branch(c, branch_id)
        b = rules.branch(snap, branch_id)
        new = rules.transition(b.status, action, b.kind)
        now = ctx.env.now()
        repo.set_status(c, branch_id, new, now)
        repo.touch_tree(c, b.tree_id, now)
        return repo.load_snapshot(c, b.tree_id).branches[branch_id]


def set_intent(ctx: Ctx, branch_id: BranchId, intent: str | None) -> Branch:
    """Req 11.4: the label may change at any time. The Framing_Block does not (Req 7.3)."""
    clean = rules.clean_intent(intent)
    with ctx.store.transaction() as c:
        snap = snapshot_of_branch(c, branch_id)
        b = rules.branch(snap, branch_id)
        if b.kind is not BranchKind.TANGENT:
            raise Conflict("Only tangents have an intent.")
        repo.set_intent(c, branch_id, clean)
        return repo.load_snapshot(c, b.tree_id).branches[branch_id]


def set_fork_point(ctx: Ctx, branch_id: BranchId, fork_at: str) -> Branch:
    """Req 9.2-9.3: only before the Branch has a Message."""
    with ctx.store.transaction() as c:
        snap = snapshot_of_branch(c, branch_id)
        b = rules.branch(snap, branch_id)
        if b.kind is not BranchKind.TANGENT or b.anchor is None or b.parent_branch_id is None:
            raise Conflict("Only tangents have a movable fork point.")
        if snap.chain(branch_id):
            raise ValidationError("fork_point", "The fork point cannot move once the branch has messages.")
        target = _fork_point_for(fork_at, b.anchor.message_id, rules.tip(snap, b.parent_branch_id))
        repo.set_fork_point(c, branch_id, target)
        return repo.load_snapshot(c, b.tree_id).branches[branch_id]
