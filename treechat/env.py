"""The clock and id source, passed in so the domain and tests never read the real ones (CLAUDE.md, Conventions)."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime


@dataclass(frozen=True, slots=True)
class Env:
    now: Callable[[], str]
    new_id: Callable[[], str]


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def system_env() -> Env:
    """Wall-clock UTC times and time-ordered UUIDv7 ids."""
    return Env(now=_now, new_id=lambda: str(uuid.uuid7()))
