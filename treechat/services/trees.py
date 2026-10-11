"""Tree-level operations (Req 1)."""

from __future__ import annotations

import sqlite3

from treechat.domain import rules
from treechat.domain.errors import NotFound
from treechat.domain.model import BranchId, TreeId, TreeSnapshot
from treechat.services.ctx import Ctx
from treechat.store import repo


def create_tree(ctx: Ctx) -> tuple[TreeId, BranchId]:
    """Req 1.1: a Tree with an empty Trunk."""
    tree_id, trunk_id = ctx.env.new_id(), ctx.env.new_id()
    with ctx.store.transaction() as c:
        repo.create_tree(c, tree_id, trunk_id, ctx.env.now())
    return tree_id, trunk_id


def rename_tree(ctx: Ctx, tree_id: TreeId, title: str) -> None:
    """Req 1.3-1.4."""
    clean = rules.clean_title(title)
    with ctx.store.transaction() as c:
        if repo.get_tree(c, tree_id) is None:
            raise NotFound(f"Unknown tree {tree_id}.")
        repo.set_title(c, tree_id, clean)


def tree_of_branch(c: sqlite3.Connection, branch_id: BranchId) -> TreeId:
    tid = repo.tree_id_of_branch(c, branch_id)
    if tid is None:
        raise NotFound(f"Unknown branch {branch_id}.")
    return tid


def tree_of_message(c: sqlite3.Connection, message_id: str) -> TreeId:
    tid = repo.tree_id_of_message(c, message_id)
    if tid is None:
        raise NotFound(f"Unknown message {message_id}.")
    return tid


def snapshot_of_branch(c: sqlite3.Connection, branch_id: BranchId) -> TreeSnapshot:
    return repo.load_snapshot(c, tree_of_branch(c, branch_id))
