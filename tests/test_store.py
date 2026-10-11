"""Store: migrations, immutability triggers, structural rules, round trips, rollback (Req 3.1, 6, 9.3, 12.8, 16)."""

from __future__ import annotations

import sqlite3
from dataclasses import replace
from pathlib import Path

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from treechat.domain.model import Anchor, Branch, BranchKind, Message, Outcome, Role, Status
from treechat.store import db, repo
from treechat.store.codec import manifest_from_json, manifest_to_json

from .builder import Builder
from .store_helpers import DUMMY_MANIFEST, Fault, persist, row_counts
from .test_domain_context import grow


@pytest.fixture
def store(tmp_path: Path) -> db.Store:
    return db.Store(tmp_path / "t.sqlite3")


def seeded(store: db.Store) -> Builder:
    """A small tree on disk: trunk with a user and assistant message, and a parked Tangent on the reply."""
    b = Builder()
    u = b.add(b.trunk, Role.USER, "tell me about caching")
    a = b.add(b.trunk, Role.ASSISTANT, "caching keys on exact prefix bytes")
    t = b.spawn(a, 0, 7, intent="why")
    b.add(t, Role.USER, "why though")
    with store.transaction() as c:
        persist(b, c)
    assert u
    return b


# --- Migrations (Req 16.1, 16.2) ------------------------------------------------------------------


def test_new_store_is_migrated_and_uses_wal(tmp_path: Path) -> None:
    s = db.Store(tmp_path / "new.sqlite3")
    with s.read() as c:
        assert c.execute("PRAGMA user_version").fetchone()[0] == db.latest_version() >= 1
        assert c.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        assert c.execute("PRAGMA foreign_keys").fetchone()[0] == 1


def test_migrate_is_safe_on_every_start_and_keeps_data(tmp_path: Path) -> None:  # Req 16.2
    path = tmp_path / "again.sqlite3"
    s = db.Store(path)
    b = seeded(s)
    before = {}
    with s.read() as c:
        before = row_counts(c)
    for _ in range(3):
        db.Store(path)  # reopening runs migrate() again
    with s.read() as c:
        assert row_counts(c) == before
        assert repo.load_snapshot(c, "tree").messages.keys() == {m.id for m in b.messages}


def test_store_from_an_older_version_is_brought_up_to_date(tmp_path: Path) -> None:
    """An empty file at version 0 (as an earlier release would leave before its first migration) upgrades."""
    path = tmp_path / "old.sqlite3"
    conn = db.connect(path)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 0
    assert db.migrate(conn) == db.latest_version()
    conn.close()


def test_store_from_a_newer_version_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "future.sqlite3"
    conn = db.connect(path)
    conn.execute(f"PRAGMA user_version = {db.latest_version() + 1}")
    conn.close()
    with pytest.raises(db.StoreTooNew):
        db.Store(path)


def test_a_failing_migration_rolls_back_completely(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    conn = db.connect(tmp_path / "bad.sqlite3")
    bad = "CREATE TABLE ok_table (id TEXT);\nCREATE TABLE ok_table (id TEXT);\n"
    monkeypatch.setattr(db, "_scripts", lambda: [(1, bad)])
    with pytest.raises(sqlite3.OperationalError):
        db.migrate(conn)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 0
    assert conn.execute("SELECT count(*) FROM sqlite_master WHERE name = 'ok_table'").fetchone()[0] == 0


# --- Immutability (Req 3.1, 16.3, 16.4) -----------------------------------------------------------


@pytest.mark.parametrize(
    "table,assignment",
    [
        ("messages", "content = 'changed'"),
        ("status_events", "at = 'x'"),
        ("generated_texts", "text = 'x'"),
    ],
)
def test_append_only_tables_reject_update_and_delete(store: db.Store, table: str, assignment: str) -> None:
    b = seeded(store)
    with store.transaction() as c:
        repo.insert_generated(c, "g1", b.trunk, "intent", "text", "fake", "t1")
    for sql in (f"UPDATE {table} SET {assignment}", f"DELETE FROM {table}"):
        with store.transaction() as c, pytest.raises(sqlite3.IntegrityError, match="immutable|append-only|cannot"):
            c.execute(sql)


def test_closings_are_append_only(store: db.Store) -> None:
    b = seeded(store)
    t = next(i for i, x in b.branches.items() if x.kind is BranchKind.TANGENT)
    with store.transaction() as c:
        repo.insert_closing(c, repo.ClosingRow("c1", t, Outcome.KEPT, "found it", None, None, "t2"))
        repo.set_status(c, t, Status.CLOSED, "t2")
    for sql in ("UPDATE closings SET conclusion = 'x'", "DELETE FROM closings"):
        with store.transaction() as c, pytest.raises(sqlite3.IntegrityError, match="append-only|cannot"):
            c.execute(sql)


def test_trees_and_branches_cannot_be_deleted(store: db.Store) -> None:  # Req 16.3
    seeded(store)
    for sql in ("DELETE FROM branches", "DELETE FROM trees"):
        with store.transaction() as c, pytest.raises(sqlite3.IntegrityError, match="cannot be deleted"):
            c.execute(sql)


def test_every_status_change_is_recorded_with_its_time(store: db.Store) -> None:  # Req 16.4
    b = seeded(store)
    t = next(i for i, x in b.branches.items() if x.kind is BranchKind.TANGENT)
    with store.transaction() as c:
        repo.set_status(c, t, Status.OPEN, "t10")
        repo.set_status(c, t, Status.PARKED, "t11")
        repo.set_status(c, t, Status.PARKED, "t12")  # no change, no event
    with store.read() as c:
        rows = c.execute(
            "SELECT from_status, to_status, at FROM status_events WHERE branch_id = ? ORDER BY id", (t,)
        ).fetchall()
        events = [tuple(r) for r in rows]
        assert events[-2:] == [("parked", "open", "t10"), ("open", "parked", "t11")]
        assert repo.load_snapshot(c, "tree").branches[t].status_since == "t11"


# --- Frozen facts (Req 7.3, 9.3) ------------------------------------------------------------------


def test_anchor_parent_and_kind_never_change(store: db.Store) -> None:
    b = seeded(store)
    t = next(i for i, x in b.branches.items() if x.kind is BranchKind.TANGENT)
    for sql in (
        "UPDATE branches SET anchor_start = 1 WHERE id = ?",
        "UPDATE branches SET anchor_quote = 'x' WHERE id = ?",
        "UPDATE branches SET parent_branch_id = id WHERE id = ?",
        "UPDATE branches SET kind = 'alternative' WHERE id = ?",
        "UPDATE branches SET created_at = 'x' WHERE id = ?",
    ):
        with store.transaction() as c, pytest.raises(sqlite3.IntegrityError, match="never change"):
            c.execute(sql, (t,))


def test_framing_is_set_once_and_never_changed(store: db.Store) -> None:  # Req 7.3
    b = Builder()
    m = b.add(b.trunk, Role.USER, "alpha beta")
    t = b.spawn(m, 0, 5)
    with store.transaction() as c:
        repo.create_tree(c, "tree", b.trunk, "t0")
        repo.insert_message(c, "tree", b.msg(m))
        repo.insert_branch(c, b.branches[t])  # framing not yet set
        repo.set_framing(c, t, "frame one")  # null -> value is allowed
    with store.transaction() as c, pytest.raises(sqlite3.IntegrityError, match="fixed once set"):
        repo.set_framing(c, t, "frame two")
    with store.transaction() as c:
        repo.set_intent(c, t, "a new label")  # the label may change; the framing may not


def test_fork_point_can_move_only_before_the_first_message(store: db.Store) -> None:  # Req 9.2, 9.3
    b = Builder()
    u = b.add(b.trunk, Role.USER, "alpha beta")
    a = b.add(b.trunk, Role.ASSISTANT, "reply")
    t = b.spawn(u, 0, 5)
    with store.transaction() as c:
        repo.create_tree(c, "tree", b.trunk, "t0")
        for m in b.messages:
            is_reply = m.role is Role.ASSISTANT
            repo.insert_message(
                c,
                "tree",
                replace(m, model="fake" if is_reply else None),
                manifest_to_json(DUMMY_MANIFEST) if is_reply else None,
            )
        repo.insert_branch(c, replace(b.branches[t], status=Status.OPEN))
    with store.transaction() as c:
        repo.set_fork_point(c, t, a)  # no messages yet: allowed
    with store.transaction() as c:
        repo.insert_message(c, "tree", Message("mX", t, a, 0, Role.USER, "hello", created_at="t5"))
    with store.transaction() as c, pytest.raises(sqlite3.IntegrityError, match="cannot move"):
        repo.set_fork_point(c, t, u)


# --- Structure (Req 4.4, 6.1, 6.2, 12.8) ----------------------------------------------------------


def test_a_closed_branch_accepts_no_messages(store: db.Store) -> None:  # Req 12.8
    b = seeded(store)
    t = next(i for i, x in b.branches.items() if x.kind is BranchKind.TANGENT)
    chain = b.chain(t)
    with store.transaction() as c:
        repo.set_status(c, t, Status.CLOSED, "t20")
    with store.transaction() as c, pytest.raises(sqlite3.IntegrityError, match="closed branch"):
        repo.insert_message(c, "tree", Message("mY", t, chain[-1], len(chain), Role.ASSISTANT, "x", "[]", "fake"), "{}")


def test_chain_must_be_contiguous_and_follow_the_fork_point(store: db.Store) -> None:  # Req 6.2
    b = seeded(store)
    t = next(i for i, x in b.branches.items() if x.kind is BranchKind.TANGENT)
    chain = b.chain(t)
    cases = [
        Message("n1", t, chain[-1], 5, Role.USER, "gap in seq", created_at="t"),
        Message("n2", t, b.chain(b.trunk)[0], len(chain), Role.USER, "wrong parent", created_at="t"),
        Message("n3", t, chain[-1], 0, Role.USER, "duplicate seq", created_at="t"),
    ]
    for m in cases:
        with store.transaction() as c, pytest.raises(sqlite3.IntegrityError):
            repo.insert_message(c, "tree", m)


def test_first_message_must_follow_the_fork_point(store: db.Store) -> None:  # Req 6.2
    b = Builder()
    u = b.add(b.trunk, Role.USER, "alpha beta")
    a = b.add(b.trunk, Role.ASSISTANT, "reply")
    t = b.spawn(u, 0, 5)  # Fork_Point = u
    with store.transaction() as c:
        repo.create_tree(c, "tree", b.trunk, "t0")
        repo.insert_message(c, "tree", b.msg(u))
        repo.insert_message(c, "tree", replace(b.msg(a), model="fake"), manifest_to_json(DUMMY_MANIFEST))
        repo.insert_branch(c, b.branches[t])
    with store.transaction() as c, pytest.raises(sqlite3.IntegrityError, match="follow the fork point"):
        repo.insert_message(c, "tree", Message("mZ", t, a, 0, Role.USER, "hi", created_at="t"))
    with store.transaction() as c:
        repo.insert_message(c, "tree", Message("mZ", t, u, 0, Role.USER, "hi", created_at="t"))


def test_only_one_trunk_per_tree_and_parents_stay_in_the_tree(store: db.Store) -> None:  # Req 6.1
    b = seeded(store)
    second_trunk = Branch("bT", "tree", None, BranchKind.TRUNK, None, None, None, Status.OPEN, None, "t")
    with store.transaction() as c, pytest.raises(sqlite3.IntegrityError):
        repo.insert_branch(c, second_trunk)
    with store.transaction() as c:
        repo.create_tree(c, "other", "bOther", "t")
    m = b.messages[0]
    foreign = Branch(
        "bF",
        "other",
        b.trunk,
        BranchKind.TANGENT,
        Anchor(m.id, 0, 3, m.content[:3]),
        m.id,
        None,
        Status.PARKED,
        None,
        "t",
    )
    with store.transaction() as c, pytest.raises(sqlite3.IntegrityError, match="different tree"):
        repo.insert_branch(c, foreign)


def test_anchor_message_must_belong_to_the_parent_branch(store: db.Store) -> None:  # Req 4.4
    b = seeded(store)
    t = next(i for i, x in b.branches.items() if x.kind is BranchKind.TANGENT)
    inner = b.chain(t)[0]  # a message of the Tangent, not of the Trunk
    bad = Branch(
        "bBad",
        "tree",
        b.trunk,
        BranchKind.TANGENT,
        Anchor(inner, 0, 3, b.msg(inner).content[:3]),
        inner,
        None,
        Status.PARKED,
        None,
        "t",
    )
    with store.transaction() as c, pytest.raises(sqlite3.IntegrityError, match="anchor message"):
        repo.insert_branch(c, bad)


def test_assistant_messages_must_carry_their_manifest(store: db.Store) -> None:  # Req 7.7
    b = seeded(store)
    t = next(i for i, x in b.branches.items() if x.kind is BranchKind.TANGENT)
    chain = b.chain(t)
    m = Message("mA", t, chain[-1], len(chain), Role.ASSISTANT, "reply", "[]", "fake")
    with store.transaction() as c, pytest.raises(sqlite3.IntegrityError):
        repo.insert_message(c, "tree", m, None)
    with store.transaction() as c:
        repo.insert_message(c, "tree", m, manifest_to_json(DUMMY_MANIFEST))
    with store.read() as c:
        assert repo.get_manifest(c, "mA") == DUMMY_MANIFEST


def test_manifest_json_round_trips() -> None:
    assert manifest_from_json(manifest_to_json(DUMMY_MANIFEST)) == DUMMY_MANIFEST


# --- Round trip (Req 16.1) ------------------------------------------------------------------------


def _norm_branch(x: Branch) -> Branch:
    return replace(x, status_since="")


def _norm_message(m: Message) -> Message:
    return replace(m, model=None)


@settings(max_examples=60, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(st.integers(0, 10_000), st.integers(1, 40))
def test_a_tree_survives_a_round_trip_through_the_store(seed: int, steps: int) -> None:
    import tempfile

    b = grow(seed, steps)
    with tempfile.TemporaryDirectory() as d:
        s = db.Store(Path(d) / "rt.sqlite3")
        with s.transaction() as c:
            persist(b, c)
        with s.read() as c:
            got = repo.load_snapshot(c, "tree")
    want = b.snapshot()
    assert {k: _norm_branch(v) for k, v in got.branches.items()} == {
        k: _norm_branch(v) for k, v in want.branches.items()
    }
    assert {k: _norm_message(v) for k, v in got.messages.items()} == {
        k: _norm_message(v) for k, v in want.messages.items()
    }
    assert got.chains == want.chains


# --- Property 11: failed operations leave no trace (Req 2.3, 16.5) --------------------------------


@settings(max_examples=60, deadline=None)
@given(st.integers(0, 10_000), st.integers(3, 30), st.integers(0, 40))
def test_property_11_a_fault_mid_operation_leaves_the_store_unchanged(seed: int, steps: int, fault_after: int) -> None:
    import tempfile

    b = grow(seed, steps)
    with tempfile.TemporaryDirectory() as d:
        s = db.Store(Path(d) / "fault.sqlite3")
        with s.read() as c:
            empty = row_counts(c)
        try:
            with s.transaction() as c:
                persist(b, c, fault_after=fault_after)
            faulted = False
        except Fault:
            faulted = True
        with s.read() as c:
            after = row_counts(c)
        if faulted:
            assert after == empty
        else:
            assert after["trees"] == 1


def test_a_failed_close_and_merge_writes_nothing(store: db.Store) -> None:  # Req 13.1: one transaction
    b = seeded(store)
    t = next(i for i, x in b.branches.items() if x.kind is BranchKind.TANGENT)
    with store.read() as c:
        before = row_counts(c)
    note = Message(
        "mN", b.trunk, b.chain(b.trunk)[-1], 2, Role.NOTE, "<tree_chat_note>x</tree_chat_note>", source_branch_id=t
    )
    with pytest.raises(Fault), store.transaction() as c:
        repo.insert_message(c, "tree", note)
        repo.insert_closing(c, repo.ClosingRow("c1", t, Outcome.MERGED, "x", b.trunk, "mN", "t"))
        repo.set_status(c, t, Status.CLOSED, "t")
        raise Fault("disk full")
    with store.read() as c:
        assert row_counts(c) == before
        assert repo.load_snapshot(c, "tree").branches[t].status is not Status.CLOSED


def test_merge_closing_requires_a_target_and_a_note(store: db.Store) -> None:  # Req 12.2, 13.1
    b = seeded(store)
    t = next(i for i, x in b.branches.items() if x.kind is BranchKind.TANGENT)
    for row in (
        repo.ClosingRow("c1", t, Outcome.MERGED, "x", None, None, "t"),
        repo.ClosingRow("c2", t, Outcome.KEPT, "", None, None, "t"),
        repo.ClosingRow("c3", t, Outcome.KEPT, None, None, None, "t"),
        repo.ClosingRow("c4", t, Outcome.KEPT, "x", b.trunk, None, "t"),
    ):
        with store.transaction() as c, pytest.raises(sqlite3.IntegrityError):
            repo.insert_closing(c, row)
    with store.transaction() as c:
        repo.insert_closing(c, repo.ClosingRow("c5", t, Outcome.ABANDONED, None, None, None, "t"))


def test_tree_list_orders_by_activity_and_counts_branches(store: db.Store) -> None:  # Req 1.2
    b = seeded(store)
    with store.transaction() as c:
        repo.create_tree(c, "newer", "bNewer", "t0001")
        repo.touch_tree(c, "newer", "t99999")
    with store.read() as c:
        rows = repo.list_trees(c)
    assert [r[0].id for r in rows] == ["newer", "tree"]
    tree_row = next(r for r in rows if r[0].id == "tree")
    assert tree_row[2] == 1 and tree_row[1] == 0  # one parked Tangent, no open non-Trunk Branches
    assert b.trunk == tree_row[0].trunk_branch_id


def test_title_check_and_generated_text_newest_wins(store: db.Store) -> None:  # Req 1.3-1.4, 11.4
    b = seeded(store)
    with store.transaction() as c:
        repo.set_title(c, "tree", "x" * 200)
    with store.transaction() as c, pytest.raises(sqlite3.IntegrityError):
        repo.set_title(c, "tree", "x" * 201)
    with store.transaction() as c:
        repo.insert_generated(c, "g1", b.trunk, "intent", "old", "fake", "t1")
        repo.insert_generated(c, "g2", b.trunk, "intent", "new", "fake", "t2")
    with store.read() as c:
        assert repo.latest_generated(c, b.trunk, "intent") == "new"
        assert repo.latest_generated(c, b.trunk, "standing") is None
