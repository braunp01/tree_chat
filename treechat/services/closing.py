"""Closing a Branch, and merging its Conclusion into an ancestor as a Note (Req 12, 13). One transaction."""

from __future__ import annotations

from dataclasses import dataclass

from treechat.domain import rules
from treechat.domain.context import note_label, note_text
from treechat.domain.errors import Busy, Conflict, ValidationError
from treechat.domain.model import Action, Branch, BranchId, BranchKind, Message, Outcome, Role
from treechat.services.ctx import Ctx
from treechat.services.messages import _append  # pyright: ignore[reportPrivateUsage]
from treechat.services.trees import snapshot_of_branch
from treechat.store import repo


@dataclass(frozen=True, slots=True)
class CloseResult:
    branch: Branch
    note: Message | None
    abandoned: tuple[BranchId, ...]


def close_branch(
    ctx: Ctx,
    branch_id: BranchId,
    outcome: Outcome,
    conclusion: str | None = None,
    merge_target: BranchId | None = None,
    abandon_descendants: bool = False,
) -> CloseResult:
    with ctx.store.transaction() as c:
        snap = snapshot_of_branch(c, branch_id)
        b = rules.branch(snap, branch_id)
        if b.kind is BranchKind.TRUNK:
            raise Conflict("The trunk cannot be closed.")  # Req 12.9
        rules.transition(b.status, Action.CLOSE, b.kind)  # already closed -> conflict (Req 10.1)
        rules.check_outcome(b.kind, outcome)  # Req 12.9
        text = rules.clean_conclusion(outcome, conclusion)  # Req 12.2-12.3
        if merge_target is not None and outcome is not Outcome.MERGED:
            raise ValidationError("merge_target", "A merge target only applies when closing as merged.")
        if ctx.is_busy(branch_id):
            raise Busy("A reply is being written in this branch; wait for it to finish.")

        to_abandon: tuple[BranchId, ...] = ()
        if abandon_descendants:  # Req 12.6
            to_abandon = tuple(
                d for d in rules.descendants(snap, branch_id) if snap.branches[d].status.value != "closed"
            )
            if any(ctx.is_busy(d) for d in to_abandon):
                raise Busy("A reply is being written in one of the branches to be abandoned.")

        now = ctx.env.now()
        note: Message | None = None
        target: BranchId | None = None
        if outcome is Outcome.MERGED:
            assert text is not None and b.anchor is not None
            target = merge_target if merge_target is not None else b.parent_branch_id
            if target not in rules.merge_targets(snap, branch_id):  # Req 13.3-13.4
                raise ValidationError("merge_target", "The merge target must be an ancestor that is not closed.")
            if ctx.is_busy(target):
                raise Busy("A reply is being written in the merge target; wait for it to finish.")  # Req 13.5
            chain = snap.chain(target)
            if chain and snap.messages[chain[-1]].role is Role.USER:
                raise Conflict("The merge target is waiting for a reply; request it before merging into it.")  # Req 2.9
            label = note_label(b.intent, repo.latest_generated(c, branch_id, "intent"), b.anchor.quoted_text)
            body = note_text(label, b.anchor.quoted_text, text)
            note = _append(ctx, c, snap, snap.branches[target], Role.NOTE, body, source_branch_id=branch_id)

        for d in to_abandon:
            repo.insert_closing(c, repo.ClosingRow(ctx.env.new_id(), d, Outcome.ABANDONED, None, None, None, now))
            repo.set_status(c, d, rules.transition(snap.branches[d].status, Action.CLOSE, snap.branches[d].kind), now)
        repo.insert_closing(
            c,
            repo.ClosingRow(ctx.env.new_id(), branch_id, outcome, text, target, note.id if note else None, now),
        )
        repo.set_status(c, branch_id, rules.transition(b.status, Action.CLOSE, b.kind), now)
        repo.touch_tree(c, b.tree_id, now)
        closed = repo.load_snapshot(c, b.tree_id).branches[branch_id]
        return CloseResult(closed, note, to_abandon)
