"""Tree-level operations (Req 1). A Tree is created by sending its first Message, its Root (Req 1.1)."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from treechat.domain import rules
from treechat.domain.errors import NotFound
from treechat.domain.model import Message, Role, TreeId, TreeSnapshot
from treechat.services.ctx import Ctx
from treechat.store import repo


@dataclass(frozen=True, slots=True)
class Created:
    tree: repo.TreeRow
    root: Message


def create_tree(ctx: Ctx, content: str) -> Created:
    """Req 1.1, 1.3: the Tree and its Root, in one transaction; the title is the Root's first 60 characters."""
    text = rules.clean_content(content)
    tree_id, root_id, now = ctx.env.new_id(), ctx.env.new_id(), ctx.env.now()
    root = Message(root_id, tree_id, None, Role.USER, text, created_at=now)
    with ctx.store.transaction() as c:
        repo.create_tree(c, tree_id, rules.title_from_root(text) or "Untitled", now)
        repo.insert_message(c, root)
        tree = repo.get_tree(c, tree_id)
    assert tree is not None
    return Created(tree, root)


def rename_tree(ctx: Ctx, tree_id: TreeId, title: str) -> repo.TreeRow:
    """Req 1.3-1.4."""
    clean = rules.clean_title(title)
    with ctx.store.transaction() as c:
        if repo.get_tree(c, tree_id) is None:
            raise NotFound(f"Unknown tree {tree_id}.")
        repo.set_title(c, tree_id, clean)
        tree = repo.get_tree(c, tree_id)
    assert tree is not None
    return tree


def list_trees(ctx: Ctx) -> list[repo.TreeRow]:
    """Req 1.2."""
    with ctx.store.read() as c:
        return repo.list_trees(c)


def tree_of_message(c: sqlite3.Connection, message_id: str) -> TreeId:
    tid = repo.tree_id_of_message(c, message_id)
    if tid is None:
        raise NotFound(f"Unknown message {message_id}.")
    return tid


def snapshot(c: sqlite3.Connection, tree_id: TreeId) -> tuple[repo.TreeRow, TreeSnapshot]:
    tree = repo.get_tree(c, tree_id)
    if tree is None:
        raise NotFound(f"Unknown tree {tree_id}.")
    return tree, repo.load_snapshot(c, tree_id)
