"""Persist a Builder's tree into a Store, the way the services will (synthetic data only)."""

from __future__ import annotations

import sqlite3
from dataclasses import replace

from treechat.domain.model import Manifest, Message, Role, Status
from treechat.store import repo
from treechat.store.codec import manifest_to_json

from .builder import Builder

DUMMY_MANIFEST = Manifest(
    entries=(), model="fake", effort="high", max_tokens=1000, system_prompt_version=1, cache_breakpoint_after=None
)


class Fault(Exception):
    """Injected store failure (Property 11)."""


def number(entity_id: str) -> int:
    return int(entity_id[1:])


def persist(b: Builder, conn: sqlite3.Connection, fault_after: int | None = None) -> int:
    """Write the whole tree in creation order; raise Fault after `fault_after` writes. Returns the write count."""
    writes = 0

    def tick() -> None:
        nonlocal writes
        writes += 1
        if fault_after is not None and writes > fault_after:
            raise Fault(f"injected fault at write {writes}")

    repo.create_tree(conn, "tree", b.trunk, b.branches[b.trunk].created_at)
    tick()
    entities: list[tuple[int, str]] = [(number(i), "b") for i in b.branches if i != b.trunk]
    entities += [(number(m.id), "m") for m in b.messages]
    by_branch = b.branches
    by_message = {m.id: m for m in b.messages}
    for n, kind in sorted(entities):
        if kind == "b":
            br = by_branch[f"b{n:04d}"]
            repo.insert_branch(conn, replace(br, status=Status.OPEN))
        else:
            m: Message = by_message[f"m{n:04d}"]
            mj = manifest_to_json(DUMMY_MANIFEST) if m.role is Role.ASSISTANT else None
            repo.insert_message(conn, "tree", replace(m, model="fake" if m.role is Role.ASSISTANT else None), mj)
        tick()
    for br in by_branch.values():
        if br.status is not Status.OPEN and br.kind.value != "trunk":
            repo.set_status(conn, br.id, br.status, "t9999")
            tick()
    return writes


def row_counts(conn: sqlite3.Connection) -> dict[str, int]:
    tables = ["trees", "branches", "messages", "status_events", "closings", "generated_texts"]
    return {t: int(conn.execute(f"SELECT count(*) FROM {t}").fetchone()[0]) for t in tables}
