"""Services and reply jobs on a real Store with the Fake provider (Req 1, 3, 4). No model calls."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from treechat.domain import rules
from treechat.domain.errors import Busy, Conflict, NotFound, ValidationError
from treechat.jobs.registry import JobRegistry
from treechat.jobs.replies import run_reply
from treechat.provider.fake import FakeProvider
from treechat.services import messages, trees
from treechat.services.ctx import Ctx
from treechat.store import repo

from .helpers import make_ctx


async def answer(ctx: Ctx, p: FakeProvider, user_id: str) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    await run_reply(ctx, p, messages.prepare_reply(ctx, user_id), events.append)
    return events


def snap(ctx: Ctx, tree_id: str):  # noqa: ANN201
    with ctx.store.read() as c:
        return repo.load_snapshot(c, tree_id)


@pytest.fixture
def ctx(tmp_path: Path) -> Ctx:
    return make_ctx(tmp_path)


async def test_a_tree_is_created_by_its_first_message(ctx: Ctx) -> None:  # Req 1.1, 1.3
    made = trees.create_tree(ctx, "  How does prefix caching work?\nAnd why " + "x" * 80)
    assert made.root.parent_id is None and made.tree.title == rules.title_from_root(made.root.content)
    assert len(made.tree.title) == 60
    with pytest.raises(ValidationError) as e:
        trees.create_tree(ctx, "   ")
    assert e.value.fields == ("content",)
    assert [t.id for t in trees.list_trees(ctx)] == [made.tree.id]  # nothing left behind by the failure


async def test_send_from_a_reply_and_branch_from_an_earlier_one(ctx: Ctx) -> None:  # Req 3.1, 3.4
    p = FakeProvider()
    t = trees.create_tree(ctx, "first")
    a1 = (await answer(ctx, p, t.root.id))[-1]["message"]["id"]
    u2 = messages.send(ctx, t.tree.id, a1, "second")
    a2 = (await answer(ctx, p, u2.id))[-1]["message"]["id"]
    u3 = messages.send(ctx, t.tree.id, a1, "a different second")  # going back to a1: a new branch
    a3 = (await answer(ctx, p, u3.id))[-1]["message"]["id"]
    s = snap(ctx, t.tree.id)
    assert s.kids(a1) == (u2.id, u3.id)
    assert [b.id for b in rules.branches(s)] == [t.root.id, u2.id, u3.id]
    with ctx.store.read() as c:
        assert [e.id for e in repo.get_manifest(c, a3).entries] == [t.root.id, a1, u3.id]  # type: ignore[union-attr]
        assert [e.id for e in repo.get_manifest(c, a2).entries] == [t.root.id, a1, u2.id]  # type: ignore[union-attr]


async def test_send_rules(ctx: Ctx) -> None:  # Req 3.2, 3.9
    p = FakeProvider()
    t = trees.create_tree(ctx, "first")
    other = trees.create_tree(ctx, "other")
    a1 = (await answer(ctx, p, t.root.id))[-1]["message"]["id"]
    oa = (await answer(ctx, p, other.root.id))[-1]["message"]["id"]
    with pytest.raises(Conflict):
        messages.send(ctx, t.tree.id, t.root.id, "after a user message")
    with pytest.raises(Conflict):
        messages.send(ctx, t.tree.id, oa, "from another tree")
    with pytest.raises(ValidationError):
        messages.send(ctx, t.tree.id, a1, "")
    with pytest.raises(NotFound):
        messages.send(ctx, "missing", a1, "x")
    assert len(snap(ctx, t.tree.id).messages) == 2


@pytest.mark.parametrize(
    ("outcome", "category"), [("fail", "provider_error"), ("refuse", "refused"), ("too_large", "context_too_large")]
)
async def test_a_failed_reply_keeps_the_question_and_can_be_retried(
    ctx: Ctx, outcome: str, category: str
) -> None:  # Req 3.5
    p = FakeProvider()
    t = trees.create_tree(ctx, "q")
    p.then(outcome)
    events = await answer(ctx, p, t.root.id)
    assert events[-1] == {"type": "error", "error": category, "message": events[-1]["message"]}
    assert list(snap(ctx, t.tree.id).messages) == [t.root.id]
    assert (await answer(ctx, p, t.root.id))[-1]["type"] == "done"


async def test_cut_off_and_fallback_replies_are_recorded(ctx: Ctx) -> None:  # Req 3.6, design.md Thinking replay
    p = FakeProvider()
    t = trees.create_tree(ctx, "q")
    p.then("truncate")
    done = (await answer(ctx, p, t.root.id))[-1]["message"]
    assert done["cut_off"] is True
    u = messages.send(ctx, t.tree.id, done["id"], "more")
    p.then("fallback")
    fb = (await answer(ctx, p, u.id))[-1]["message"]
    assert fb["model"] != ctx.settings.model


async def test_one_reply_per_question(ctx: Ctx) -> None:  # Req 3.3, 5.3
    p = FakeProvider()
    t = trees.create_tree(ctx, "q")
    prepared = messages.prepare_reply(ctx, t.root.id)
    await answer(ctx, p, t.root.id)
    with pytest.raises(Conflict):
        messages.prepare_reply(ctx, t.root.id)
    result = await p.generate(prepared.request, lambda _t: asyncio.sleep(0))
    with pytest.raises(Conflict):
        messages.finish_reply(ctx, prepared, result)  # a late duplicate is refused, not stored


async def test_the_registry_runs_one_job_per_question(tmp_path: Path) -> None:  # Req 3.7, 3.8
    reg = JobRegistry()
    base = make_ctx(tmp_path)
    ctx = Ctx(base.store, base.env, base.settings, reg.is_busy)
    p = FakeProvider()
    p.gate = asyncio.Event()
    a = trees.create_tree(ctx, "one")
    b = trees.create_tree(ctx, "two")
    job = reg.start_reply(ctx, p, a.root.id)
    with pytest.raises(Busy):
        reg.start_reply(ctx, p, a.root.id)
    other = reg.start_reply(ctx, p, b.root.id)  # other questions are unaffected
    p.gate.set()
    await reg.drain()
    events = [e async for e in job.stream()]  # a late subscriber gets the whole story
    assert events[0]["type"] == "started" and events[-1]["type"] == "done"
    assert other.finished and not reg.is_busy(a.root.id)
