"""Reply jobs: one per Branch, independent of any browser connection (Req 2.2, 2.5, 2.6, 13.5). No AI credits."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from treechat.domain.errors import Busy
from treechat.domain.model import Outcome
from treechat.jobs.registry import JobRegistry
from treechat.provider.base import OnDelta, ProviderResult
from treechat.provider.fake import FakeProvider
from treechat.services import closing, messages
from treechat.services.ctx import Ctx
from treechat.store.db import Store

from .svc_helpers import SETTINGS, counting_env, counts, new_tree, snapshot


def setup(tmp_path: Path) -> tuple[Ctx, JobRegistry, FakeProvider]:
    reg = JobRegistry()
    ctx = Ctx(Store(tmp_path / "jobs.sqlite3"), counting_env(), SETTINGS, reg.is_busy)
    return ctx, reg, FakeProvider(chunk=4)


async def collect(job: Any) -> list[dict[str, Any]]:
    return [e async for e in job.stream()]


async def test_a_reply_streams_started_deltas_done_and_is_persisted(tmp_path: Path) -> None:  # Req 2.2
    ctx, reg, fake = setup(tmp_path)
    tid, trunk = new_tree(ctx)
    messages.send_message(ctx, trunk, "hello there")
    job = reg.start_reply(ctx, fake, trunk)
    events = await collect(job)
    assert events[0]["type"] == "started" and events[-1]["type"] == "done"
    assert all(e["type"] == "delta" for e in events[1:-1]) and len(events) > 3
    saved = snapshot(ctx, tid).messages[events[-1]["message"]["id"]]
    assert "".join(e["text"] for e in events[1:-1]) == saved.content
    assert not reg.is_busy(trunk) and reg.get(trunk) is None


async def test_only_one_reply_runs_per_branch_but_other_branches_are_free(tmp_path: Path) -> None:  # Req 2.5
    ctx, reg, fake = setup(tmp_path)
    tid, trunk = new_tree(ctx)
    messages.send_message(ctx, trunk, "hello")
    fake.gate = asyncio.Event()
    job = reg.start_reply(ctx, fake, trunk)
    assert reg.is_busy(trunk)
    with pytest.raises(Busy):
        reg.start_reply(ctx, fake, trunk)
    with pytest.raises(Busy):
        messages.send_message(ctx, trunk, "more")
    fake.gate.set()
    assert (await collect(job))[-1]["type"] == "done"
    assert not reg.is_busy(trunk) and tid
    messages.send_message(ctx, trunk, "now it is allowed")


async def test_two_branches_reply_at_the_same_time(tmp_path: Path) -> None:  # Req 2.5: other Branches are unaffected
    ctx, reg, fake = setup(tmp_path)
    tid, trunk = new_tree(ctx)
    messages.send_message(ctx, trunk, "first")
    fake.gate = asyncio.Event()
    first = reg.start_reply(ctx, fake, trunk)
    u = snapshot(ctx, tid).chain(trunk)[0]
    alt = messages.edit_message(ctx, u, "an alternative")
    second = reg.start_reply(ctx, fake, alt.id)
    assert reg.is_busy(trunk) and reg.is_busy(alt.id)
    fake.gate.set()
    a, b = await asyncio.gather(collect(first), collect(second))
    assert a[-1]["type"] == b[-1]["type"] == "done"
    snap = snapshot(ctx, tid)
    assert len(snap.chain(trunk)) == 2 and len(snap.chain(alt.id)) == 2


async def test_the_reply_finishes_and_is_saved_when_the_browser_disconnects(tmp_path: Path) -> None:  # Req 2.6
    ctx, reg, fake = setup(tmp_path)
    tid, trunk = new_tree(ctx)
    messages.send_message(ctx, trunk, "tell me a long story please")
    job = reg.start_reply(ctx, fake, trunk)
    seen: list[dict[str, Any]] = []
    async for e in job.stream():
        seen.append(e)
        if e["type"] == "delta":
            break  # the browser goes away mid-reply
    await reg.drain()
    assert len(snapshot(ctx, tid).chain(trunk)) == 2
    again = await collect(job)  # reopening the branch shows it
    assert again[0]["type"] == "started" and again[-1]["type"] == "done"
    assert "".join(e["text"] for e in again if e["type"] == "delta") == again[-1]["message"]["content"]


async def test_a_late_subscriber_gets_a_catch_up_chunk_then_the_rest(tmp_path: Path) -> None:  # Req 2.6
    ctx, reg, fake = setup(tmp_path)
    _, trunk = new_tree(ctx)
    messages.send_message(ctx, trunk, "hello")
    job = reg.start_reply(ctx, fake, trunk)
    first = job.stream()
    received: list[dict[str, Any]] = []
    for _ in range(3):
        received.append(await anext(first))
    late = await collect(job)  # attaches mid-reply
    rest = [e async for e in first]
    full = [*received, *rest]
    assert late[0]["type"] == "started" and late[-1] == full[-1]
    joined_late = "".join(e["text"] for e in late if e["type"] == "delta")
    joined_full = "".join(e["text"] for e in full if e["type"] == "delta")
    assert joined_late == joined_full == full[-1]["message"]["content"]
    await reg.drain()


async def test_a_failed_reply_ends_with_an_error_event_and_frees_the_branch(tmp_path: Path) -> None:  # Req 2.3
    ctx, reg, fake = setup(tmp_path)
    tid, trunk = new_tree(ctx)
    messages.send_message(ctx, trunk, "hello")
    before = counts(ctx)
    fake.then("refuse")
    events = await collect(reg.start_reply(ctx, fake, trunk))
    assert events[-1] == {"type": "error", "error": "refused", "message": "The request was declined."}
    assert counts(ctx) == before and not reg.is_busy(trunk)
    assert len(snapshot(ctx, tid).chain(trunk)) == 1


class ExplodingProvider(FakeProvider):
    async def generate(self, request: dict[str, Any], on_delta: OnDelta) -> ProviderResult:
        raise RuntimeError("bug in the provider")


async def test_an_unexpected_crash_still_ends_the_stream_cleanly(tmp_path: Path) -> None:
    ctx, reg, _ = setup(tmp_path)
    _, trunk = new_tree(ctx)
    messages.send_message(ctx, trunk, "hello")
    events = await collect(reg.start_reply(ctx, ExplodingProvider(), trunk))
    assert events[-1]["type"] == "error" and events[-1]["error"] == "provider_error"
    assert not reg.is_busy(trunk)


async def test_a_branch_cannot_be_closed_or_merged_into_while_a_reply_is_running(tmp_path: Path) -> None:  # Req 13.5
    ctx, reg, fake = setup(tmp_path)
    tid, trunk = new_tree(ctx)
    messages.send_message(ctx, trunk, "first")
    await collect(reg.start_reply(ctx, fake, trunk))
    from treechat.services import branches

    a = snapshot(ctx, tid).chain(trunk)[-1]
    t = branches.spawn_tangent(ctx, a, 0, 4, snapshot(ctx, tid).messages[a].content[:4])
    messages.send_message(ctx, t.id, "tangent question")
    await collect(reg.start_reply(ctx, fake, t.id))
    messages.send_message(ctx, trunk, "second")
    fake.gate = asyncio.Event()
    running = reg.start_reply(ctx, fake, trunk)
    with pytest.raises(Busy):
        closing.close_branch(ctx, t.id, Outcome.MERGED, "c")  # the merge target is busy
    fake.gate.set()
    await collect(running)
    closing.close_branch(ctx, t.id, Outcome.KEPT, "c")


async def test_background_work_is_tracked_until_it_finishes(tmp_path: Path) -> None:
    _, reg, _ = setup(tmp_path)
    done: list[int] = []

    async def work() -> None:
        await asyncio.sleep(0)
        done.append(1)

    reg.spawn_background(work())
    await reg.drain()
    assert done == [1]
