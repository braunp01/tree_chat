"""Connections, transactions and migrations. The only code that opens the database (CLAUDE.md, Conventions)."""

from __future__ import annotations

import sqlite3
from collections.abc import Generator, Iterator
from contextlib import contextmanager
from importlib import resources
from pathlib import Path

MIGRATIONS_PACKAGE = "treechat.store.migrations"


class StoreTooNew(Exception):
    """The file was written by a newer version of the app; refuse to touch it."""


class IncompatibleStore(Exception):
    """The file is a v1 Store (Branch records); v2 never opens it (design.md, Store)."""


def _scripts() -> list[tuple[int, str]]:
    found: list[tuple[int, str]] = []
    for entry in resources.files(MIGRATIONS_PACKAGE).iterdir():
        name = entry.name
        if name.endswith(".sql") and name[:3].isdigit():
            found.append((int(name[:3]), entry.read_text(encoding="utf-8")))
    found.sort()
    expected = list(range(1, len(found) + 1))
    if [n for n, _ in found] != expected:
        raise RuntimeError(f"migrations must be numbered 001.. without gaps, found {[n for n, _ in found]}")
    return found


def latest_version() -> int:
    return len(_scripts())


def _statements(script: str) -> Iterator[str]:
    """Split a script into statements; triggers contain semicolons, so ask SQLite where one ends."""
    buf = ""
    for line in script.splitlines(keepends=True):
        buf += line
        if sqlite3.complete_statement(buf):
            stmt = buf.strip()
            buf = ""
            if stmt and not all(ln.strip().startswith("--") or not ln.strip() for ln in stmt.splitlines()):
                yield stmt
    if buf.strip() and not all(ln.strip().startswith("--") or not ln.strip() for ln in buf.splitlines()):
        raise RuntimeError("migration ends with an incomplete statement")


def connect(path: str | Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path), isolation_level=None, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 10000")
    return conn


def migrate(conn: sqlite3.Connection) -> int:
    """Bring the file up to date, one transaction per script. Safe to run on every start (Req 7.2)."""
    current = int(conn.execute("PRAGMA user_version").fetchone()[0])
    if conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'branches'").fetchone():
        raise IncompatibleStore("this data file was made by Tree Chat v1; v2 uses a new file (TREECHAT_DB)")
    scripts = _scripts()
    if current > len(scripts):
        raise StoreTooNew(f"this data file is version {current}, but this app only knows version {len(scripts)}")
    for version, script in scripts:
        if version <= current:
            continue
        conn.execute("BEGIN IMMEDIATE")
        try:
            for stmt in _statements(script):
                conn.execute(stmt)
            conn.execute(f"PRAGMA user_version = {version}")  # transactional: rolls back with the script
            conn.execute("COMMIT")
        except BaseException:
            conn.execute("ROLLBACK")
            raise
    return len(scripts)


class Store:
    """A database file. Each operation gets its own connection, so request threads never share one."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = connect(self.path)
        try:
            conn.execute("PRAGMA journal_mode = WAL")  # persists in the file
            conn.execute("PRAGMA synchronous = NORMAL")
            migrate(conn)
        finally:
            conn.close()

    @contextmanager
    def read(self) -> Generator[sqlite3.Connection]:
        conn = connect(self.path)
        try:
            yield conn
        finally:
            conn.close()

    @contextmanager
    def transaction(self) -> Generator[sqlite3.Connection]:
        """All writes of one operation, or none of them (Req 7.3)."""
        conn = connect(self.path)
        try:
            conn.execute("BEGIN IMMEDIATE")
            try:
                yield conn
            except BaseException:
                conn.execute("ROLLBACK")
                raise
            else:
                conn.execute("COMMIT")
        finally:
            conn.close()
