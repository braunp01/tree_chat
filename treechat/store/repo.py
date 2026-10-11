"""Row-level reads and writes. No decisions: services decide, this module records (design.md, Layers)."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from treechat.domain.model import (
    Anchor,
    Branch,
    BranchId,
    BranchKind,
    Manifest,
    Message,
    MessageId,
    Outcome,
    Role,
    Status,
    TreeId,
    TreeSnapshot,
)
from treechat.store.codec import manifest_from_json


@dataclass(frozen=True, slots=True)
class TreeRow:
    id: TreeId
    title: str | None
    trunk_branch_id: BranchId
    created_at: str
    last_activity_at: str


def _tree_row(r: sqlite3.Row) -> TreeRow:
    return TreeRow(r["id"], r["title"], r["trunk_branch_id"], r["created_at"], r["last_activity_at"])


# --- Trees ----------------------------------------------------------------------------------------


def create_tree(conn: sqlite3.Connection, tree_id: TreeId, trunk_id: BranchId, now: str) -> None:
    """Req 1.1: a Tree with a Trunk that has no Messages."""
    conn.execute(
        "INSERT INTO trees (id, title, trunk_branch_id, created_at, last_activity_at) VALUES (?, NULL, ?, ?, ?)",
        (tree_id, trunk_id, now, now),
    )
    conn.execute(
        "INSERT INTO branches (id, tree_id, parent_branch_id, kind, status, created_at) "
        "VALUES (?, ?, NULL, 'trunk', 'open', ?)",
        (trunk_id, tree_id, now),
    )
    _status_event(conn, trunk_id, None, Status.OPEN, now)


def set_title(conn: sqlite3.Connection, tree_id: TreeId, title: str) -> None:
    conn.execute("UPDATE trees SET title = ? WHERE id = ?", (title, tree_id))


def touch_tree(conn: sqlite3.Connection, tree_id: TreeId, now: str) -> None:
    conn.execute("UPDATE trees SET last_activity_at = ? WHERE id = ?", (now, tree_id))


def get_tree(conn: sqlite3.Connection, tree_id: TreeId) -> TreeRow | None:
    r = conn.execute("SELECT * FROM trees WHERE id = ?", (tree_id,)).fetchone()
    return None if r is None else _tree_row(r)


def list_trees(conn: sqlite3.Connection) -> list[tuple[TreeRow, int, int]]:
    """Req 1.2: most recently active first, with counts of open and parked Branches."""
    rows = conn.execute(
        """SELECT t.*,
                  (SELECT count(*) FROM branches b WHERE b.tree_id = t.id AND b.status = 'open'
                       AND b.kind != 'trunk') AS n_open,
                  (SELECT count(*) FROM branches b WHERE b.tree_id = t.id AND b.status = 'parked') AS n_parked
           FROM trees t ORDER BY t.last_activity_at DESC, t.id DESC"""
    ).fetchall()
    return [(_tree_row(r), r["n_open"], r["n_parked"]) for r in rows]


# --- Branches -------------------------------------------------------------------------------------


def insert_branch(conn: sqlite3.Connection, b: Branch) -> None:
    a = b.anchor
    conn.execute(
        "INSERT INTO branches (id, tree_id, parent_branch_id, kind, anchor_message_id, anchor_start, anchor_end, "
        "anchor_quote, fork_point_message_id, intent, status, framing_text, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            b.id,
            b.tree_id,
            b.parent_branch_id,
            b.kind.value,
            a.message_id if a else None,
            a.start if a else None,
            a.end if a else None,
            a.quoted_text if a else None,
            b.fork_point_message_id,
            b.intent,
            b.status.value,
            b.framing_text,
            b.created_at,
        ),
    )
    _status_event(conn, b.id, None, b.status, b.created_at)


def _status_event(conn: sqlite3.Connection, branch_id: BranchId, old: Status | None, new: Status, at: str) -> None:
    conn.execute(
        "INSERT INTO status_events (branch_id, from_status, to_status, at) VALUES (?, ?, ?, ?)",
        (branch_id, old.value if old else None, new.value, at),
    )


def set_status(conn: sqlite3.Connection, branch_id: BranchId, new: Status, now: str) -> None:
    """Req 16.4: every Status change is recorded with its time."""
    row = conn.execute("SELECT status FROM branches WHERE id = ?", (branch_id,)).fetchone()
    old = Status(row["status"])
    if old is new:
        return
    conn.execute("UPDATE branches SET status = ? WHERE id = ?", (new.value, branch_id))
    _status_event(conn, branch_id, old, new, now)


def set_intent(conn: sqlite3.Connection, branch_id: BranchId, intent: str | None) -> None:
    conn.execute("UPDATE branches SET intent = ? WHERE id = ?", (intent, branch_id))


def set_fork_point(conn: sqlite3.Connection, branch_id: BranchId, message_id: MessageId | None) -> None:
    conn.execute("UPDATE branches SET fork_point_message_id = ? WHERE id = ?", (message_id, branch_id))


def set_framing(conn: sqlite3.Connection, branch_id: BranchId, text: str) -> None:
    conn.execute("UPDATE branches SET framing_text = ? WHERE id = ?", (text, branch_id))


# --- Messages -------------------------------------------------------------------------------------


def insert_message(conn: sqlite3.Connection, tree_id: TreeId, m: Message, manifest_json: str | None = None) -> None:
    conn.execute(
        "INSERT INTO messages (id, tree_id, branch_id, parent_message_id, seq, role, content, provider_blocks, "
        "model, stop_reason, manifest, source_branch_id, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            m.id,
            tree_id,
            m.branch_id,
            m.parent_message_id,
            m.seq,
            m.role.value,
            m.content,
            m.blocks_json,
            m.model,
            m.stop_reason,
            manifest_json,
            m.source_branch_id,
            m.created_at,
        ),
    )


def get_manifest(conn: sqlite3.Connection, message_id: MessageId) -> Manifest | None:
    r = conn.execute("SELECT manifest FROM messages WHERE id = ?", (message_id,)).fetchone()
    return None if r is None or r["manifest"] is None else manifest_from_json(r["manifest"])


def message_preview(conn: sqlite3.Connection, message_id: MessageId, limit: int = 200) -> str | None:
    r = conn.execute("SELECT substr(content, 1, ?) AS p FROM messages WHERE id = ?", (limit, message_id)).fetchone()
    return None if r is None else r["p"]


# --- Closings and generated text ------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ClosingRow:
    id: str
    branch_id: BranchId
    outcome: Outcome
    conclusion: str | None
    merge_target_branch_id: BranchId | None
    note_message_id: MessageId | None
    closed_at: str


def insert_closing(conn: sqlite3.Connection, c: ClosingRow) -> None:
    conn.execute(
        "INSERT INTO closings (id, branch_id, outcome, conclusion, merge_target_branch_id, note_message_id, closed_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (c.id, c.branch_id, c.outcome.value, c.conclusion, c.merge_target_branch_id, c.note_message_id, c.closed_at),
    )


def closings_for(conn: sqlite3.Connection, branch_id: BranchId) -> list[ClosingRow]:
    rows = conn.execute("SELECT * FROM closings WHERE branch_id = ? ORDER BY closed_at, id", (branch_id,)).fetchall()
    return [
        ClosingRow(
            r["id"],
            r["branch_id"],
            Outcome(r["outcome"]),
            r["conclusion"],
            r["merge_target_branch_id"],
            r["note_message_id"],
            r["closed_at"],
        )
        for r in rows
    ]


def insert_generated(
    conn: sqlite3.Connection, gid: str, branch_id: BranchId, kind: str, text: str, model: str, now: str
) -> None:
    conn.execute(
        "INSERT INTO generated_texts (id, branch_id, kind, text, model, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (gid, branch_id, kind, text, model, now),
    )


def latest_generated(conn: sqlite3.Connection, branch_id: BranchId, kind: str) -> str | None:
    """Req 11.4: the newest row of each kind is the one shown."""
    r = conn.execute(
        "SELECT text FROM generated_texts WHERE branch_id = ? AND kind = ? ORDER BY created_at DESC, id DESC LIMIT 1",
        (branch_id, kind),
    ).fetchone()
    return None if r is None else r["text"]


# --- Snapshot -------------------------------------------------------------------------------------


def load_snapshot(conn: sqlite3.Connection, tree_id: TreeId) -> TreeSnapshot:
    """Everything the domain needs about one Tree, as immutable records."""
    branches: list[Branch] = []
    for r in conn.execute(
        """SELECT b.*, (SELECT e.at FROM status_events e WHERE e.branch_id = b.id ORDER BY e.id DESC LIMIT 1) AS since
           FROM branches b WHERE b.tree_id = ? ORDER BY b.created_at, b.id""",
        (tree_id,),
    ):
        anchor = (
            None
            if r["anchor_message_id"] is None
            else Anchor(r["anchor_message_id"], r["anchor_start"], r["anchor_end"], r["anchor_quote"])
        )
        branches.append(
            Branch(
                id=r["id"],
                tree_id=r["tree_id"],
                parent_branch_id=r["parent_branch_id"],
                kind=BranchKind(r["kind"]),
                anchor=anchor,
                fork_point_message_id=r["fork_point_message_id"],
                intent=r["intent"],
                status=Status(r["status"]),
                framing_text=r["framing_text"],
                created_at=r["created_at"],
                status_since=r["since"] or r["created_at"],
            )
        )
    messages = [
        Message(
            id=r["id"],
            branch_id=r["branch_id"],
            parent_message_id=r["parent_message_id"],
            seq=r["seq"],
            role=Role(r["role"]),
            content=r["content"],
            blocks_json=r["provider_blocks"],
            model=r["model"],
            stop_reason=r["stop_reason"],
            source_branch_id=r["source_branch_id"],
            created_at=r["created_at"],
        )
        for r in conn.execute(
            "SELECT id, branch_id, parent_message_id, seq, role, content, provider_blocks, model, stop_reason, "
            "source_branch_id, created_at FROM messages WHERE tree_id = ?",
            (tree_id,),
        )
    ]
    return TreeSnapshot.build(branches, messages)
