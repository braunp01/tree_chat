"""The Store refuses whatever the shape and immutability rules forbid (Req 5, 7)."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from treechat.store import repo
from treechat.store.db import IncompatibleStore, Store, _scripts, _statements, connect, latest_version, migrate

from .helpers import manifest_json, reply, user


@pytest.fixture
def store(tmp_path: Path) -> Store:
    s = Store(tmp_path / "s.sqlite3")
    with s.transaction() as c:
        repo.create_tree(c, "T", "a tree", "t0")
        repo.create_tree(c, "U", "another", "t0")
        repo.insert_message(c, user("u1", "T", None))
        repo.insert_message(c, reply("a1", "T", "u1"), manifest_json("u1"))
    return s


def migrate_to(conn: sqlite3.Connection, version: int) -> None:
    """Build the schema of an earlier version, as a Store made by that version would have it."""
    for v, script in _scripts():
        if v <= version:
            for stmt in _statements(script):
                conn.execute(stmt)
    conn.execute(f"PRAGMA user_version = {version}")


def fails(store: Store, sql: str, *args: object) -> None:
    with pytest.raises(sqlite3.DatabaseError):
        with store.transaction() as c:
            c.execute(sql, args)


def insert_fails(store: Store, m, manifest: str | None = None) -> None:  # noqa: ANN001
    with pytest.raises(sqlite3.DatabaseError):
        with store.transaction() as c:
            repo.insert_message(c, m, manifest)


def test_a_valid_tree_round_trips(store: Store) -> None:
    with store.transaction() as c:
        repo.insert_message(c, user("u2", "T", "a1"))
        repo.insert_message(c, user("u3", "T", "a1"))  # a fork: two children of one reply
    with store.read() as c:
        snap = repo.load_snapshot(c, "T")
        assert snap.root_id == "u1" and snap.kids("a1") == ("u2", "u3")
        assert repo.get_manifest(c, "a1") is not None and repo.get_manifest(c, "u1") is None


@pytest.mark.parametrize(
    "bad",
    [
        user("x", "T", None),  # a second Root (Req 5.3)
        user("x", "T", "u1"),  # user after user
        reply("x", "T", "a1"),  # assistant after assistant
        reply("x", "T", "u1"),  # a second Reply to the same user Message
        user("x", "U", "a1"),  # parent in another Tree
        user("x", "T", "missing"),  # parent that does not exist
    ],
)
def test_shape_rules_are_enforced_by_the_database(store: Store, bad) -> None:  # noqa: ANN001 - Req 5.3
    insert_fails(store, bad, manifest_json("u1") if bad.role.value == "assistant" else None)


def test_a_root_must_be_a_user_message(store: Store) -> None:
    insert_fails(store, reply("x", "U", "a1"), manifest_json("u1"))
    with pytest.raises(sqlite3.DatabaseError):
        with store.transaction() as c:
            c.execute(
                "INSERT INTO messages (id, tree_id, parent_id, role, content, provider_blocks, model, manifest, "
                "created_at) VALUES ('x', 'U', NULL, 'assistant', 'hi', '[]', 'm', '{}', 't')"
            )


def test_a_reply_must_carry_blocks_model_and_manifest(store: Store) -> None:  # Req 4.4
    with store.transaction() as c:
        repo.insert_message(c, user("u2", "T", "a1"))
    insert_fails(store, reply("a2", "T", "u2"), None)


def test_empty_content_is_refused(store: Store) -> None:  # Req 3.9
    insert_fails(store, user("x", "T", "a1", "   "))


def test_nothing_is_ever_changed_or_deleted(store: Store) -> None:  # Req 5.1-5.2
    fails(store, "UPDATE messages SET content = 'changed' WHERE id = 'u1'")
    fails(store, "UPDATE messages SET manifest = '{}' WHERE id = 'a1'")
    fails(store, "DELETE FROM messages WHERE id = 'a1'")
    fails(store, "DELETE FROM trees WHERE id = 'U'")
    fails(store, "UPDATE trees SET created_at = 'x' WHERE id = 'T'")
    with store.transaction() as c:
        repo.set_title(c, "T", "renamed")  # a title may change (Req 1.3)
        assert repo.get_tree(c, "T").title == "renamed"  # type: ignore[union-attr]
    fails(store, "UPDATE trees SET title = '  ' WHERE id = 'T'")  # Req 1.4


def test_a_failed_operation_keeps_none_of_its_writes(store: Store) -> None:  # Req 7.3
    with pytest.raises(sqlite3.DatabaseError):
        with store.transaction() as c:
            repo.insert_message(c, user("u2", "T", "a1"))
            repo.insert_message(c, user("bad", "T", "u2"))
    with store.read() as c:
        assert "u2" not in repo.load_snapshot(c, "T").messages


def test_migration_is_safe_to_run_again(tmp_path: Path) -> None:  # Req 7.2
    Store(tmp_path / "s.sqlite3")
    conn = connect(tmp_path / "s.sqlite3")
    assert migrate(conn) == latest_version()
    assert int(conn.execute("PRAGMA user_version").fetchone()[0]) == latest_version()


def test_a_v1_store_is_never_opened(tmp_path: Path) -> None:  # design.md, Store
    conn = connect(tmp_path / "old.sqlite3")
    conn.execute("CREATE TABLE branches (id TEXT)")
    conn.execute("PRAGMA user_version = 1")
    conn.close()
    with pytest.raises(IncompatibleStore):
        Store(tmp_path / "old.sqlite3")


def test_trees_are_listed_most_recently_active_first(store: Store) -> None:  # Req 1.2
    with store.transaction() as c:
        repo.touch_tree(c, "U", "t9")
        assert [t.id for t in repo.list_trees(c)] == ["U", "T"]


# --- Branch_Summaries (Req 9.3) ---------------------------------------------------------------------


def _summary(mid: str, text: str = "Caching basics for HTTP") -> repo.SummaryRow:
    return repo.SummaryRow(mid, text, "fake-haiku", (mid,), 1, "t5")


def test_a_summary_round_trips_and_the_first_one_wins(store: Store) -> None:  # Req 9.3
    with store.transaction() as c:
        assert repo.insert_summary(c, _summary("u1")) is True
        assert repo.insert_summary(c, _summary("u1", "A different name")) is False
    with store.read() as c:
        assert repo.summaries_for_tree(c, "T") == {"u1": _summary("u1")}
        assert repo.summaries_for_tree(c, "U") == {}


def test_a_summary_is_never_changed_or_deleted(store: Store) -> None:  # Req 9.3
    with store.transaction() as c:
        repo.insert_summary(c, _summary("u1"))
    fails(store, "UPDATE branch_summaries SET summary = 'x'")
    fails(store, "DELETE FROM branch_summaries")


@pytest.mark.parametrize("text", ["", "x" * 61])
def test_a_summary_has_one_to_sixty_characters(store: Store, text: str) -> None:  # Req 9.2
    with pytest.raises(sqlite3.DatabaseError):
        with store.transaction() as c:
            repo.insert_summary(c, _summary("u1", text))


def test_only_a_user_message_can_be_named(store: Store) -> None:  # a Branch starts at a user Message
    with pytest.raises(sqlite3.DatabaseError):
        with store.transaction() as c:
            repo.insert_summary(c, _summary("a1"))
    with pytest.raises(sqlite3.DatabaseError):
        with store.transaction() as c:
            repo.insert_summary(c, _summary("missing"))


def test_a_store_from_before_summaries_is_brought_up_to_date(tmp_path: Path) -> None:  # Req 7.2
    conn = connect(tmp_path / "v1.sqlite3")
    migrate_to(conn, 1)
    conn.execute("INSERT INTO trees VALUES ('T', 'a tree', 't0', 't0')")
    conn.close()
    s = Store(tmp_path / "v1.sqlite3")
    with s.read() as c:
        assert [t.id for t in repo.list_trees(c)] == ["T"]
        assert int(c.execute("PRAGMA user_version").fetchone()[0]) == latest_version() >= 2
