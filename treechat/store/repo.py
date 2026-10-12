"""Row-level reads and writes. No decisions: services decide, this module records (design.md, Architecture)."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass

from treechat.domain.model import Manifest, Message, MessageId, Role, TreeId, TreeSnapshot
from treechat.store.codec import manifest_from_json


@dataclass(frozen=True, slots=True)
class TreeRow:
    id: TreeId
    title: str
    created_at: str
    last_activity_at: str


def _tree_row(r: sqlite3.Row) -> TreeRow:
    return TreeRow(r["id"], r["title"], r["created_at"], r["last_activity_at"])


# --- Trees ----------------------------------------------------------------------------------------


def create_tree(conn: sqlite3.Connection, tree_id: TreeId, title: str, now: str) -> None:
    conn.execute(
        "INSERT INTO trees (id, title, created_at, last_activity_at) VALUES (?, ?, ?, ?)", (tree_id, title, now, now)
    )


def set_title(conn: sqlite3.Connection, tree_id: TreeId, title: str) -> None:
    conn.execute("UPDATE trees SET title = ? WHERE id = ?", (title, tree_id))


def touch_tree(conn: sqlite3.Connection, tree_id: TreeId, now: str) -> None:
    conn.execute("UPDATE trees SET last_activity_at = ? WHERE id = ?", (now, tree_id))


def get_tree(conn: sqlite3.Connection, tree_id: TreeId) -> TreeRow | None:
    r = conn.execute("SELECT * FROM trees WHERE id = ?", (tree_id,)).fetchone()
    return None if r is None else _tree_row(r)


def list_trees(conn: sqlite3.Connection) -> list[TreeRow]:
    """Req 1.2: most recently active first."""
    rows = conn.execute("SELECT * FROM trees ORDER BY last_activity_at DESC, id DESC").fetchall()
    return [_tree_row(r) for r in rows]


# --- Messages -------------------------------------------------------------------------------------


def insert_message(conn: sqlite3.Connection, m: Message, manifest_json: str | None = None) -> None:
    conn.execute(
        "INSERT INTO messages (id, tree_id, parent_id, role, content, provider_blocks, model, stop_reason, manifest, "
        "created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            m.id,
            m.tree_id,
            m.parent_id,
            m.role.value,
            m.content,
            m.blocks_json,
            m.model,
            m.stop_reason,
            manifest_json,
            m.created_at,
        ),
    )


def tree_id_of_message(conn: sqlite3.Connection, message_id: MessageId) -> TreeId | None:
    r = conn.execute("SELECT tree_id FROM messages WHERE id = ?", (message_id,)).fetchone()
    return None if r is None else r["tree_id"]


def get_manifest(conn: sqlite3.Connection, message_id: MessageId) -> Manifest | None:
    r = conn.execute("SELECT manifest FROM messages WHERE id = ?", (message_id,)).fetchone()
    return None if r is None or r["manifest"] is None else manifest_from_json(r["manifest"])


def load_snapshot(conn: sqlite3.Connection, tree_id: TreeId) -> TreeSnapshot:
    """Every Message of one Tree, as immutable records."""
    rows = conn.execute(
        "SELECT id, tree_id, parent_id, role, content, provider_blocks, model, stop_reason, created_at "
        "FROM messages WHERE tree_id = ?",
        (tree_id,),
    )
    return TreeSnapshot.build(
        [
            Message(
                id=r["id"],
                tree_id=r["tree_id"],
                parent_id=r["parent_id"],
                role=Role(r["role"]),
                content=r["content"],
                blocks_json=r["provider_blocks"],
                model=r["model"],
                stop_reason=r["stop_reason"],
                created_at=r["created_at"],
            )
            for r in rows
        ]
    )


# --- Branch_Summaries (Req 9) -----------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SummaryRow:
    message_id: MessageId
    summary: str
    model: str
    source: tuple[MessageId, ...]
    prompt_version: int
    created_at: str


def insert_summary(conn: sqlite3.Connection, s: SummaryRow) -> bool:
    """Req 9.3: the first summary for a Branch wins; a later one is dropped, never written over. True if inserted."""
    cur = conn.execute(
        "INSERT INTO branch_summaries (message_id, summary, model, source, prompt_version, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT (message_id) DO NOTHING",  # only a duplicate is ignored, never a CHECK
        (s.message_id, s.summary, s.model, json.dumps(list(s.source)), s.prompt_version, s.created_at),
    )
    return cur.rowcount == 1


def summaries_for_tree(conn: sqlite3.Connection, tree_id: TreeId) -> dict[MessageId, SummaryRow]:
    rows = conn.execute(
        "SELECT s.* FROM branch_summaries s JOIN messages m ON m.id = s.message_id WHERE m.tree_id = ?", (tree_id,)
    )
    return {
        r["message_id"]: SummaryRow(
            r["message_id"],
            r["summary"],
            r["model"],
            tuple(json.loads(r["source"])),
            r["prompt_version"],
            r["created_at"],
        )
        for r in rows
    }
