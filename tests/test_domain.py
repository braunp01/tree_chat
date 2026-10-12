"""Properties 3, 4, 5 and 7 over randomly grown message trees (design.md). Pure; no model calls."""

from __future__ import annotations

import json
import random
from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from treechat.domain import context, render, rules
from treechat.domain.errors import Conflict, NotFound, ValidationError
from treechat.domain.model import Message, Role, TreeSnapshot
from treechat.provider.fake import check_request_shape

from .helpers import SETTINGS, reply, user

TEXTS = ["alpha beta", "one two three", "émigré 😀 text", "x", "the quick brown fox"]


def grow(seed: int, steps: int, other_model_every: int = 0) -> TreeSnapshot:
    """A random Tree: each step either answers a pending user Message or asks from a random reply (often a fork)."""
    rnd = random.Random(seed)
    msgs: list[Message] = [user("m0", "T", None, rnd.choice(TEXTS), "t00000")]
    for i in range(1, steps + 1):
        at = f"t{i:05d}"
        pending = [m for m in msgs if m.role is Role.USER and not any(c.parent_id == m.id for c in msgs)]
        replies = [m for m in msgs if m.role is Role.ASSISTANT]
        if pending and (not replies or rnd.random() < 0.55):
            p = rnd.choice(pending)
            model = "other-model" if other_model_every and i % other_model_every == 0 else "fake-model"
            msgs.append(reply(f"m{i}", "T", p.id, rnd.choice(TEXTS), at, model))
        elif replies:
            msgs.append(user(f"m{i}", "T", rnd.choice(replies).id, rnd.choice(TEXTS), at))
    return TreeSnapshot.build(msgs)


trees = st.builds(grow, st.integers(0, 10_000), st.integers(0, 40), st.sampled_from([0, 3]))


def users(snap: TreeSnapshot) -> list[str]:
    return [m.id for m in snap.messages.values() if m.role is Role.USER]


def strip_cache(req: dict[str, Any]) -> list[Any]:
    turns = json.loads(json.dumps(req["messages"]))
    for t in turns:
        for b in t["content"]:
            b.pop("cache_control", None)
    return turns


@settings(max_examples=300)
@given(trees)
def test_context_is_exactly_the_path(snap: TreeSnapshot) -> None:  # Property 3, Req 4.1
    for u in users(snap):
        m = context.assemble(snap, u, SETTINGS)
        ids = [e.id for e in m.entries]
        assert ids == list(rules.path(snap, u))
        assert ids[0] == snap.root_id and ids[-1] == u
        assert [e.role for e in m.entries] == [Role.USER if i % 2 == 0 else Role.ASSISTANT for i in range(len(ids))]


@settings(max_examples=300)
@given(trees)
def test_rendering_is_deterministic_and_valid_for_the_real_api(snap: TreeSnapshot) -> None:  # Property 4, Req 4.2
    for u in users(snap):
        m = context.assemble(snap, u, SETTINGS)
        a = render.request_bytes(render.render(m, snap.messages))
        b = render.request_bytes(render.render(context.assemble(snap, u, SETTINGS), snap.messages))
        assert a == b
        check_request_shape(render.render(m, snap.messages))


@settings(max_examples=300)
@given(trees)
def test_paths_that_share_a_prefix_share_its_bytes(snap: TreeSnapshot) -> None:  # Property 4, Req 4.3
    us = users(snap)
    for x in us:
        for y in us:
            px, py = rules.path(snap, x), rules.path(snap, y)
            common = 0
            while common < min(len(px), len(py)) and px[common] == py[common]:
                common += 1
            rx = strip_cache(render.render(context.assemble(snap, x, SETTINGS), snap.messages))
            ry = strip_cache(render.render(context.assemble(snap, y, SETTINGS), snap.messages))
            assert rx[:common] == ry[:common]


@settings(max_examples=300)
@given(trees)
def test_thinking_replay_is_valid(snap: TreeSnapshot) -> None:  # Property 5, Req 4.2, 5.1
    """Every replayed reply is byte-identical to how it was stored (thinking dropped only for another model), and
    the request bytes before it equal the request that produced it."""
    for u in users(snap):
        req = render.render(context.assemble(snap, u, SETTINGS), snap.messages)
        turns = strip_cache(req)
        path = rules.path(snap, u)
        for i, mid in enumerate(path):
            msg = snap.messages[mid]
            if msg.role is not Role.ASSISTANT:
                continue
            stored = json.loads(msg.blocks_json or "[]")
            if msg.model != SETTINGS.model:
                stored = [b for b in stored if b["type"] != "thinking"]
            assert turns[i]["content"] == stored
            producer = strip_cache(render.render(context.assemble(snap, path[i - 1], SETTINGS), snap.messages))
            assert turns[:i] == producer


@settings(max_examples=300)
@given(trees)
def test_branches_partition_the_tree(snap: TreeSnapshot) -> None:  # Property 7, Req 6
    bs = rules.branches(snap)
    seen = [mid for b in bs for mid in b.message_ids]
    assert sorted(seen) == sorted(snap.messages)  # every Message in exactly one Branch
    owner = {mid: b.id for b in bs for mid in b.message_ids}
    for b in bs:
        first = snap.messages[b.id]
        assert b.message_ids[0] == b.id
        if first.parent_id is None:
            assert b.parent_branch_id is None
        else:
            assert len(snap.kids(first.parent_id)) > 1  # a Branch starts at a child of a Fork
            assert b.parent_branch_id == owner[first.parent_id]
            parent = {x.id: x for x in bs}[b.parent_branch_id or ""]
            assert parent.message_ids[-1] == first.parent_id  # it forks from the end of its parent Branch
        for a, c in zip(b.message_ids, b.message_ids[1:], strict=False):
            assert snap.messages[c].parent_id == a and len(snap.kids(a)) == 1  # a chain through single children
        assert len(snap.kids(b.message_ids[-1])) != 1  # ends at a Fork or a Leaf


def test_known_tree_branches_and_default_point() -> None:  # Req 2.2, 6
    msgs = [
        user("u1", "T", None, at="t1"),
        reply("a1", "T", "u1", at="t2"),
        user("u2", "T", "a1", at="t3"),
        reply("a2", "T", "u2", at="t4"),
        user("u3", "T", "a1", at="t5"),  # a fork at a1
        reply("a3", "T", "u3", at="t6"),
        user("u4", "T", "a3", at="t7"),  # pending
    ]
    snap = TreeSnapshot.build(msgs)
    assert [(b.id, b.parent_branch_id, b.message_ids) for b in rules.branches(snap)] == [
        ("u1", None, ("u1", "a1")),
        ("u2", "u1", ("u2", "a2")),
        ("u3", "u1", ("u3", "a3", "u4")),
    ]
    assert rules.default_point(snap) == "a3"
    assert rules.latest_reply_below(snap, "a1") == "a3" and rules.latest_reply_below(snap, "a2") is None  # Req 2.4
    assert rules.default_point(TreeSnapshot.build([user("r", "T", None)])) == "r"


def test_rules_for_sending_and_replying() -> None:  # Req 3.2, 3.3, 5.3
    snap = TreeSnapshot.build(
        [user("u1", "T", None, at="t1"), reply("a1", "T", "u1", at="t2"), user("u2", "T", "a1", at="t3")]
    )
    rules.check_parent(snap, "a1")
    with pytest.raises(Conflict):
        rules.check_parent(snap, "u2")  # not a reply
    with pytest.raises(Conflict):
        rules.check_parent(snap, "elsewhere")  # not in this Tree
    rules.check_can_reply(snap, "u2")
    with pytest.raises(Conflict):
        rules.check_can_reply(snap, "u1")  # already answered
    with pytest.raises(Conflict):
        rules.check_can_reply(snap, "a1")
    with pytest.raises(NotFound):
        rules.path(snap, "missing")


@pytest.mark.parametrize(("text", "ok"), [("x", True), (" " * 3, False), ("a" * 100_000, True), ("a" * 100_001, False)])
def test_content_limits(text: str, ok: bool) -> None:  # Req 3.9
    if ok:
        assert rules.clean_content(text) == text
    else:
        with pytest.raises(ValidationError) as e:
            rules.clean_content(text)
        assert e.value.fields == ("content",)


@pytest.mark.parametrize(("text", "ok"), [("t", True), ("  ", False), ("a" * 200, True), ("a" * 201, False)])
def test_title_limits(text: str, ok: bool) -> None:  # Req 1.4
    if ok:
        assert rules.clean_title(text) == text
    else:
        with pytest.raises(ValidationError):
            rules.clean_title(text)


def test_title_from_root_is_one_line_of_60() -> None:  # Req 1.3
    assert rules.title_from_root("  hello\n  world  " + "x" * 100) == ("hello world " + "x" * 100)[:60]


@settings(max_examples=200)
@given(trees)
def test_the_cache_breakpoint_sits_just_before_the_new_message(snap: TreeSnapshot) -> None:  # Req 4.3
    """So a new branch from a reply reads everything up to and including that reply from the cache."""
    for u in users(snap):
        turns = render.render(context.assemble(snap, u, SETTINGS), snap.messages)["messages"]
        marked = [(i, j) for i, t in enumerate(turns) for j, b in enumerate(t["content"]) if "cache_control" in b]
        if len(turns) == 1:
            assert marked == []
        else:
            last_before = len(turns) - 2
            assert marked == [(last_before, len(turns[last_before]["content"]) - 1)]
            assert turns[last_before]["content"][-1]["type"] != "thinking"
