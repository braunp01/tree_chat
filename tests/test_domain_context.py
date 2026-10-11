"""Properties 1, 3-7 and 12 over randomly grown trees (Req 3.5, 4.4, 4.7, 7.1-7.9, 11.5). Pure; no model calls."""

from __future__ import annotations

import json
import random
from dataclasses import replace
from typing import Any

from hypothesis import given, settings
from hypothesis import strategies as st

from treechat.domain import context, render, rules
from treechat.domain.model import (
    BranchKind,
    FramingEntry,
    Manifest,
    MessageEntry,
    Role,
    Settings,
    Status,
    TreeSnapshot,
)

from .builder import Builder

SETTINGS = Settings(model="fake-model", effort="high", max_tokens=1000)
TEXTS = ["alpha beta gamma", "one two", "émigré 😀 text", "x", "the quick brown fox jumps"]


def grow(seed: int, steps: int) -> Builder:
    """Apply `steps` random valid operations; the same seed always gives the same tree."""
    rnd = random.Random(seed)
    b = Builder()
    for _ in range(steps):
        snap = b.snapshot()
        live = [x for x in snap.branches.values() if x.status is not Status.CLOSED]
        target = rnd.choice(live)
        chain = snap.chain(target.id)
        last_role = snap.messages[chain[-1]].role if chain else None
        op = rnd.choice(["user", "user", "reply", "spawn", "spawn", "tipspawn", "alt", "note", "close"])
        if op == "user" and last_role in (None, Role.ASSISTANT, Role.NOTE):
            b.add(target.id, Role.USER, rnd.choice(TEXTS))
        elif op == "reply" and last_role is Role.USER:
            b.add(target.id, Role.ASSISTANT, rnd.choice(TEXTS))
        elif op in ("spawn", "tipspawn") and snap.messages:
            m = snap.messages[rnd.choice(sorted(snap.messages))]
            if m.role is Role.NOTE:
                continue
            n = len(m.content)
            s = rnd.randrange(n)
            e = rnd.randrange(s + 1, n + 1)
            b.spawn(m.id, s, e, intent=rnd.choice([None, "why?", "check this"]), fork_at_tip=op == "tipspawn")
        elif op == "alt":
            cand = [m for m in snap.messages.values() if m.role in (Role.USER, Role.ASSISTANT)]
            if cand:
                b.alternative(rnd.choice(cand).id)
        elif op == "note" and last_role is Role.ASSISTANT and target.kind is not BranchKind.ALTERNATIVE:
            src = [x for x in snap.branches.values() if x.parent_branch_id == target.id]
            if src:
                b.add(target.id, Role.NOTE, "<tree_chat_note>concluded</tree_chat_note>", source=src[0].id)
        elif op == "close":
            idle = [x for x in live if x.kind is not BranchKind.TRUNK]
            if idle:
                b.set_status(rnd.choice(idle).id, Status.CLOSED)
    return b


trees = st.builds(grow, st.integers(0, 10_000), st.integers(1, 45))


def ctx(snap: TreeSnapshot, bid: str) -> tuple[Any, ...]:
    return context.context_entries(snap, bid)


def flatten(request: dict[str, Any]) -> list[tuple[str, str]]:
    """(role, canonical block) for every block, in order."""
    out: list[tuple[str, str]] = []
    for t in request["messages"]:
        content = t["content"]
        blocks = content if isinstance(content, list) else [content]
        for blk in blocks:
            out.append((t["role"], json.dumps(blk, sort_keys=True, ensure_ascii=False)))
    return out


# --- Property 1: strict tree and linear chains (Req 4.4, 6.1-6.3) --------------------------------------


@settings(max_examples=300, deadline=None)
@given(trees)
def test_property_1_strict_tree_and_linear_chains(b: Builder) -> None:
    snap = b.snapshot()
    roots = [x for x in snap.branches.values() if x.parent_branch_id is None]
    assert [r.id for r in roots] == [b.trunk]
    for x in snap.branches.values():
        assert len(rules.ancestors(snap, x.id)) <= len(snap.branches)  # terminates: no cycles
        chain = snap.chain(x.id)
        assert [snap.messages[m].seq for m in chain] == list(range(len(chain)))
        for i, mid in enumerate(chain):
            expected = chain[i - 1] if i else x.fork_point_message_id
            assert snap.messages[mid].parent_message_id == expected
        if x.parent_branch_id is not None:
            parent = snap.branches[x.parent_branch_id]
            assert x.anchor is not None
            assert snap.messages[x.anchor.message_id].branch_id == parent.id  # Req 4.4
            if x.fork_point_message_id is not None:
                # Req 6.3: the Fork_Point lies on the path to the parent's Tip as it stands.
                path = rules.message_path(snap, rules.tip(snap, parent.id))
                assert x.fork_point_message_id in path or x.fork_point_message_id == parent.fork_point_message_id


# --- Properties 3, 4: determinism and shared prefixes (Req 7.4, 7.5) -----------------------------------


@settings(max_examples=300, deadline=None)
@given(trees, st.randoms(use_true_random=False))
def test_property_3_assembly_and_rendering_are_deterministic(b: Builder, rnd: random.Random) -> None:
    snap = b.snapshot()
    shuffled_branches = list(b.branches.values())
    shuffled_messages = list(b.messages)
    rnd.shuffle(shuffled_branches)
    rnd.shuffle(shuffled_messages)
    snap2 = TreeSnapshot.build(shuffled_branches, shuffled_messages)
    for bid in snap.branches:
        m1, m2 = context.assemble(snap, bid, SETTINGS), context.assemble(snap2, bid, SETTINGS)
        assert m1 == m2
        assert render.request_bytes(render.render(m1, snap.messages)) == render.request_bytes(
            render.render(m2, snap2.messages)
        )


@settings(max_examples=300, deadline=None)
@given(trees)
def test_property_4_siblings_share_a_byte_identical_prefix(b: Builder) -> None:
    snap = b.snapshot()
    groups: dict[tuple[str | None, str | None], list[str]] = {}
    for x in snap.branches.values():
        if x.kind is BranchKind.TANGENT:
            groups.setdefault((x.parent_branch_id, x.fork_point_message_id), []).append(x.id)
    for ids in groups.values():
        reqs = []
        for bid in ids:
            if not snap.chain(bid):
                continue  # a reply is only ever requested once the Branch has a Message
            man = context.assemble(snap, bid, SETTINGS)
            n = len(context.inherited_prefix(snap, bid))
            # Blocks of the prefix = blocks of (prefix + the Branch's first own entry) minus that entry's one block.
            with_first = replace(man, entries=man.entries[: n + 1])
            k = len(flatten(render.render(with_first, snap.messages))) - 1 if n else 0
            reqs.append((flatten(render.render(man, snap.messages))[:k], man.cache_breakpoint_after))
        assert all(r == reqs[0] for r in reqs)


# --- Property 5: inherit means what the parent knew (Req 7.1) ------------------------------------------


def _truncated(snap: TreeSnapshot, branch_id: str, keep_through: str | None) -> TreeSnapshot:
    """The Tree as it was when `branch_id`'s Tip was `keep_through`, with every later Message of it removed."""
    chain = snap.chain(branch_id)
    drop = set(chain[chain.index(keep_through) + 1 :]) if keep_through in chain else set(chain)
    msgs = [m for m in snap.messages.values() if m.id not in drop]
    return TreeSnapshot.build(list(snap.branches.values()), msgs)


@settings(max_examples=300, deadline=None)
@given(trees)
def test_property_5_inherited_prefix_is_what_the_parent_knew(b: Builder) -> None:
    snap = b.snapshot()
    for x in snap.branches.values():
        if x.parent_branch_id is None:
            assert context.inherited_prefix(snap, x.id) == ()
            continue
        earlier = _truncated(snap, x.parent_branch_id, x.fork_point_message_id)
        assert context.inherited_prefix(snap, x.id) == ctx(earlier, x.parent_branch_id)


@settings(max_examples=200, deadline=None)
@given(trees)
def test_inherited_prefix_carries_every_ancestors_framing(b: Builder) -> None:
    """Glossary: not simply the Messages on the path; every ancestor Tangent's Framing_Block is included."""
    snap = b.snapshot()
    for x in snap.branches.values():
        prefix = context.inherited_prefix(snap, x.id)
        in_prefix = {e.branch_id for e in prefix if isinstance(e, FramingEntry)}
        for a in rules.ancestors(snap, x.id):
            anc = snap.branches[a]
            first_in_prefix = snap.chain(a) and (
                snap.chain(a)[0] in {e.id for e in prefix if isinstance(e, MessageEntry)}
            )
            if anc.kind is BranchKind.TANGENT and anc.framing_text and first_in_prefix:
                assert a in in_prefix


# --- Property 6: contexts only grow (Req 7.1, 7.6) -----------------------------------------------------


@settings(max_examples=150, deadline=None)
@given(st.integers(0, 10_000), st.integers(2, 40))
def test_property_6_contexts_only_grow(seed: int, steps: int) -> None:
    """Replay a grown tree one Message at a time: each Branch's Context extends its earlier one, and its
    Inherited_Prefix never changes once the Branch has a Message."""
    full = grow(seed, steps)
    branches = list(full.branches.values())
    seen: dict[str, tuple[Any, ...]] = {}
    prefixes: dict[str, tuple[Any, ...]] = {}
    for i in range(len(full.messages) + 1):
        snap = TreeSnapshot.build(branches, full.messages[:i])
        for bid in snap.branches:
            if not _consistent(snap, bid):
                continue
            now = ctx(snap, bid)
            if bid in seen:
                assert now[: len(seen[bid])] == seen[bid]
            seen[bid] = now
            if snap.chain(bid):
                pre = context.inherited_prefix(snap, bid)
                assert prefixes.setdefault(bid, pre) == pre  # Req 7.6


def _consistent(snap: TreeSnapshot, bid: str) -> bool:
    """A Branch in a partial replay may reference Messages not yet added; skip those states."""
    try:
        context.context_entries(snap, bid)
        return True
    except KeyError, ValueError:
        return False


# --- Property 7: replay is byte-identical and thinking blocks are kept (Req 7.4, 7.6) ------------------


def test_property_7_companion_child_request_replays_parent_reply_byte_for_byte() -> None:
    b = Builder()
    u = b.add(b.trunk, Role.USER, "tell me about caching")
    a = b.add(b.trunk, Role.ASSISTANT, "caching keys on exact prefix bytes")
    t = b.spawn(a, 0, 7, intent="does this hold for Anthropic?")
    q = b.add(t, Role.USER, "does it?")
    snap = b.snapshot()
    man = context.assemble(snap, t, SETTINGS)
    req = render.render(man, snap.messages)
    stored = json.loads(b.msg(a).blocks_json or "[]")
    assistant_turns = [x for x in req["messages"] if x["role"] == "assistant"]
    assert assistant_turns[0]["content"][: len(stored)] == stored or any(
        blk.get("type") == "thinking" and blk["signature"] == f"sig-{a}" for blk in assistant_turns[0]["content"]
    )
    # The thinking block is present and untouched (apart from the cache marker on a text block).
    assert assistant_turns[0]["content"][0] == stored[0]
    # Order: user, assistant, user (the tangent's first message), system framing.
    assert [x["role"] for x in req["messages"]] == ["user", "assistant", "user", "system"]
    assert u in {e.id for e in man.entries if isinstance(e, MessageEntry)}
    assert q in {e.id for e in man.entries if isinstance(e, MessageEntry)}


@settings(max_examples=300, deadline=None)
@given(trees)
def test_property_7_replayed_blocks_are_unchanged_and_requests_extend(b: Builder) -> None:
    snap = b.snapshot()
    for x in snap.branches:
        man = context.assemble(snap, x, SETTINGS)
        req = render.render(man, snap.messages)
        want = {e.id for e in man.entries if isinstance(e, MessageEntry) and snap.messages[e.id].role is Role.ASSISTANT}
        got = [
            blk
            for t in req["messages"]
            if t["role"] == "assistant"
            for blk in t["content"]
            if blk["type"] == "thinking"
        ]
        assert len(got) == len(want)
        for blk in got:
            assert blk["signature"].removeprefix("sig-") in want
            assert set(blk) == {"type", "thinking", "signature"}  # no cache marker, no edits
        # System messages follow a user turn and never lead (provider rule for mid-conversation system messages).
        roles = [t["role"] for t in req["messages"]]
        for i, r in enumerate(roles):
            if r == "system":
                assert i > 0 and roles[i - 1] == "user"


@settings(max_examples=200, deadline=None)
@given(trees)
def test_a_reply_request_is_a_prefix_extension_of_the_previous_one(b: Builder) -> None:
    """Within a Branch, each later request's blocks start with the earlier request's blocks (cache + thinking)."""
    snap = b.snapshot()
    for bid in snap.branches:
        chain = snap.chain(bid)
        previous: list[tuple[str, str]] | None = None
        for k in range(1, len(chain) + 1):
            sub = TreeSnapshot.build(
                list(snap.branches.values()),
                [m for m in snap.messages.values() if m.branch_id != bid or m.seq < k],
            )
            man = context.assemble(sub, bid, SETTINGS)
            # Drop cache markers (they move as the prefix is fixed) and compare content only.
            flat = [(r, _strip_cache(c)) for r, c in flatten(render.render(man, sub.messages))]
            if previous is not None and sub.messages[chain[k - 1]].role is not Role.NOTE:
                assert flat[: len(previous)] == previous
            previous = flat


def _strip_cache(block_json: str) -> str:
    try:
        d = json.loads(block_json)
    except json.JSONDecodeError:
        return block_json
    if isinstance(d, dict):
        d.pop("cache_control", None)
        return json.dumps(d, sort_keys=True, ensure_ascii=False)
    return block_json


# --- Property 12 and framing facts (Req 7.3, 11.5) -----------------------------------------------------


@settings(max_examples=300, deadline=None)
@given(trees)
def test_property_12_only_messages_and_user_framing_reach_the_model(b: Builder) -> None:
    snap = b.snapshot()
    for bid in snap.branches:
        for e in ctx(snap, bid):
            if isinstance(e, FramingEntry):
                owner = snap.branches[e.branch_id]
                assert owner.anchor is not None
                assert e.text == context.framing_text(owner.anchor.quoted_text, owner.intent)
            else:
                assert e.id in snap.messages


def test_framing_follows_first_user_message_and_never_uses_a_generated_intent() -> None:  # Req 7.1, 7.3, 11.5
    b = Builder()
    m = b.add(b.trunk, Role.USER, "alpha beta")
    t = b.spawn(m, 0, 5)  # no Intent
    first = b.add(t, Role.USER, "hi")
    snap = b.snapshot()
    es = ctx(snap, t)
    assert [type(e).__name__ for e in es] == ["MessageEntry", "MessageEntry", "FramingEntry"]
    assert es[1] == MessageEntry(first, Role.USER)
    f = es[2]
    assert isinstance(f, FramingEntry) and "did not state an intent" in f.text and "<anchor>alpha</anchor>" in f.text


def test_framing_is_fixed_at_first_message() -> None:  # Req 7.3
    b = Builder()
    m = b.add(b.trunk, Role.USER, "alpha beta")
    t = b.spawn(m, 0, 5, intent="one")
    b.add(t, Role.USER, "hi")
    before = b.branches[t].framing_text
    b.branches[t] = replace(b.branches[t], intent="changed label")
    b.add(t, Role.ASSISTANT, "ok")
    assert [e for e in ctx(b.snapshot(), t) if isinstance(e, FramingEntry)][0].text == before
    assert before is not None and "one" in before


def test_alternative_of_a_tangents_first_message_keeps_its_framing() -> None:  # Req 3.5
    b = Builder()
    m = b.add(b.trunk, Role.USER, "alpha beta")
    t = b.spawn(m, 0, 5, intent="why")
    first = b.add(t, Role.USER, "hi")
    alt = b.alternative(first)
    b.add(alt, Role.USER, "hello instead")
    es = ctx(b.snapshot(), alt)
    assert [type(e).__name__ for e in es] == ["MessageEntry", "MessageEntry", "FramingEntry"]
    assert isinstance(es[2], FramingEntry) and es[2].branch_id == t


def test_alternative_of_a_later_message_inherits_framing_through_its_prefix() -> None:  # Req 3.5
    b = Builder()
    m = b.add(b.trunk, Role.USER, "alpha beta")
    t = b.spawn(m, 0, 5)
    b.add(t, Role.USER, "hi")
    reply = b.add(t, Role.ASSISTANT, "ok")
    alt = b.alternative(reply)
    b.add(alt, Role.ASSISTANT, "different")
    es = ctx(b.snapshot(), alt)
    assert sum(isinstance(e, FramingEntry) for e in es) == 1


def test_note_is_labelled_and_never_attributed_to_the_user() -> None:  # Req 7.9, 13.2
    b = Builder()
    u = b.add(b.trunk, Role.USER, "alpha beta")
    b.add(b.trunk, Role.ASSISTANT, "reply")
    text = context.note_text("why?", "alpha " * 60, "It holds.")
    n = b.add(b.trunk, Role.NOTE, text)
    snap = b.snapshot()
    req = render.render(context.assemble(snap, b.trunk, SETTINGS), snap.messages)
    last = req["messages"][-1]
    assert last["role"] == "user" and last["content"][0]["text"].startswith('<tree_chat_note from_branch="why?"')
    quoted = text.split('anchored_on="')[1].split('">')[0]
    assert len(quoted) == 200  # Req 13.2: the quote is cut to 200 characters
    assert n in {e.id for e in context.context_entries(snap, b.trunk) if isinstance(e, MessageEntry)} and u


def test_note_label_falls_back_in_order() -> None:  # Req 13.2
    assert context.note_label("mine", "gen", "q" * 100) == "mine"
    assert context.note_label(None, "gen", "q" * 100) == "gen"
    assert context.note_label(None, None, "q" * 100) == "q" * 80


def test_note_attributes_are_escaped() -> None:
    t = context.note_text('say "hi" <b>\nnow', 'a & "b"', "c")
    assert t.splitlines()[0].count('"') == 4
    assert "&quot;" in t and "&amp;" in t and "&lt;" in t


def test_a_new_note_does_not_change_an_existing_child_prefix() -> None:  # Req 13.6
    b = Builder()
    m = b.add(b.trunk, Role.USER, "alpha beta")
    r = b.add(b.trunk, Role.ASSISTANT, "reply")
    t = b.spawn(r, 0, 5)
    before = context.inherited_prefix(b.snapshot(), t)
    b.add(b.trunk, Role.NOTE, "note")
    b.add(b.trunk, Role.USER, "later")
    assert context.inherited_prefix(b.snapshot(), t) == before
    assert m


def test_tip_fork_sees_notes_but_anchor_fork_does_not() -> None:  # Req 13.6, 4.10 and design "Reach of a Note"
    b = Builder()
    b.add(b.trunk, Role.USER, "alpha beta")
    r = b.add(b.trunk, Role.ASSISTANT, "reply here")
    n = b.add(b.trunk, Role.NOTE, "note")
    at_anchor = b.spawn(r, 0, 5)
    at_tip = b.spawn(r, 0, 5, fork_at_tip=True)
    snap = b.snapshot()
    ids = lambda bid: [e.id for e in context.inherited_prefix(snap, bid) if isinstance(e, MessageEntry)]  # noqa: E731
    assert n not in ids(at_anchor)
    assert n in ids(at_tip)


def test_deep_chain_assembles_without_recursion_limits() -> None:  # Req 4.7
    b = Builder()
    cur = b.trunk
    for _ in range(1500):
        m = b.add(cur, Role.USER, "hello there")
        cur = b.spawn(m, 0, 5)
    b.add(cur, Role.USER, "bottom")
    snap = b.snapshot()
    assert len(ctx(snap, cur)) > 1500


def test_cache_breakpoint_marks_the_last_inherited_block() -> None:  # Req 7.5
    b = Builder()
    b.add(b.trunk, Role.USER, "alpha beta")
    r = b.add(b.trunk, Role.ASSISTANT, "reply here")
    t = b.spawn(r, 0, 5)
    b.add(t, Role.USER, "child question")
    snap = b.snapshot()
    man: Manifest = context.assemble(snap, t, SETTINGS)
    assert man.cache_breakpoint_after == 1
    req = render.render(man, snap.messages)
    marked = [(i, blk) for i, tn in enumerate(req["messages"]) for blk in tn["content"] if "cache_control" in blk]
    assert len(marked) == 1 and marked[0][0] == 1 and marked[0][1]["type"] == "text"
    assert req["cache_control"] == {"type": "ephemeral"}


def test_framing_followed_by_a_user_turn_travels_as_user_text() -> None:
    """A tangent forked from a user Message with no reply yet: its framing cannot be a system message."""
    b = Builder()
    m = b.add(b.trunk, Role.USER, "alpha beta")
    t = b.spawn(m, 0, 5)
    first = b.add(t, Role.USER, "hi")
    child = b.spawn(first, 0, 2)  # forked at the Tangent's first message: prefix ends with its framing
    b.add(child, Role.USER, "deeper")
    snap = b.snapshot()
    man = context.assemble(snap, child, SETTINGS)
    assert isinstance(man.entries[man.cache_breakpoint_after or 0], FramingEntry)
    req = render.render(man, snap.messages)
    # One user turn (trunk text, hi, parent framing, deeper) then the child's own framing, last, as a system message.
    assert [t_["role"] for t_ in req["messages"]] == ["user", "system"]
    blocks = req["messages"][0]["content"]
    assert [x["text"][:17] for x in blocks][2] == "<tree_chat_framin"
    marked = [i for i, blk in enumerate(blocks) if "cache_control" in blk]
    assert marked == [2]  # breakpoint 1 sits on the last inherited block, the framing text


def test_breakpoint_skips_a_system_framing_entry() -> None:  # a system message cannot carry cache_control
    b = Builder()
    m = b.add(b.trunk, Role.USER, "alpha beta")
    t = b.spawn(m, 0, 5)
    first = b.add(t, Role.USER, "hi")
    b.add(t, Role.ASSISTANT, "reply")
    child = b.spawn(first, 0, 2)  # prefix: m, first, framing(t) followed by the child's own user turn
    snap = b.snapshot()
    man = context.assemble(snap, child, SETTINGS)
    assert man.cache_breakpoint_after is not None
    req = render.render(man, snap.messages)
    assert all("cache_control" not in str(t_["content"]) for t_ in req["messages"] if t_["role"] == "system")


def test_system_prompt_is_frozen_text_and_versioned() -> None:
    man = context.assemble(Builder().snapshot(), "b0001", SETTINGS)
    assert man.system_prompt_version == 1
    assert "tree_chat_framing" in render.SYSTEM_PROMPTS[1] and "tree_chat_note" in render.SYSTEM_PROMPTS[1]
