"""Moving Branches between Statuses (Req 10, 12.7). Spawning Tangents was retired on 12 Oct 2026 (Req 4)."""

from __future__ import annotations

from treechat.domain import rules
from treechat.domain.model import Action, Branch, BranchId
from treechat.services.ctx import Ctx
from treechat.services.trees import snapshot_of_branch
from treechat.store import repo


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
