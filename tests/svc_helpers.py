"""Shared setup for service and job tests: a real store, a counting clock and a fake provider (no AI credits)."""

from __future__ import annotations

import itertools
from collections.abc import Callable
from pathlib import Path
from typing import Any

from treechat.domain.model import BranchId, Settings
from treechat.env import Env
from treechat.jobs.replies import run_reply
from treechat.provider.fake import FakeProvider
from treechat.services import trees
from treechat.services.ctx import Ctx
from treechat.services.messages import prepare_reply
from treechat.store import repo
from treechat.store.db import Store

SETTINGS = Settings(model="fake-model", effort="high", max_tokens=1000)


def counting_env() -> Env:
    n = itertools.count(1)
    return Env(now=lambda: f"t{next(n):08d}", new_id=lambda: f"id{next(n):08d}")


def make_ctx(path: Path, is_busy: Callable[[BranchId], bool] | None = None) -> Ctx:
    store = Store(path / "svc.sqlite3")
    return Ctx(store, counting_env(), SETTINGS, is_busy) if is_busy else Ctx(store, counting_env(), SETTINGS)


def new_tree(ctx: Ctx) -> tuple[str, str]:
    return trees.create_tree(ctx)


async def reply(ctx: Ctx, provider: FakeProvider, branch_id: BranchId) -> list[dict[str, Any]]:
    """Request and finish one reply; returns the events a browser would have seen."""
    events: list[dict[str, Any]] = []
    await run_reply(ctx, provider, prepare_reply(ctx, branch_id), events.append)
    return events


def snapshot(ctx: Ctx, tree_id: str):  # noqa: ANN201 - TreeSnapshot, kept loose for brevity in tests
    with ctx.store.read() as c:
        return repo.load_snapshot(c, tree_id)


def counts(ctx: Ctx) -> dict[str, int]:
    with ctx.store.read() as c:
        return {
            t: int(c.execute(f"SELECT count(*) FROM {t}").fetchone()[0])
            for t in ("trees", "branches", "messages", "status_events", "closings", "generated_texts")
        }
