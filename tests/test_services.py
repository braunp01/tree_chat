"""Operations end to end against a real store and the fake provider (Req 1-4, 7, 9-13). No AI credits."""

from __future__ import annotations

from pathlib import Path

import pytest

from treechat.domain import context
from treechat.domain.errors import Busy, Conflict, NotFound, ValidationError
from treechat.domain.model import Action, BranchKind, FramingEntry, MessageEntry, Outcome, Role, Status
from treechat.jobs.replies import draft_conclusion, generate_intent, generate_standing
from treechat.provider.fake import FakeProvider
from treechat.services import branches, closing, messages, trees
from treechat.services.ctx import Ctx
from treechat.store import repo

from .svc_helpers import counts, make_ctx, new_tree, reply, snapshot


@pytest.fixture
def ctx(tmp_path: Path) -> Ctx:
    return make_ctx(tmp_path)


@pytest.fixture
def fake() -> FakeProvider:
    return FakeProvider()


async def chat(ctx: Ctx, fake: FakeProvider, branch: str, text: str) -> tuple[str, str]:
    """Send a user message and get the reply; returns (user id, assistant id)."""
    u = messages.send_message(ctx, branch, text)
    events = await reply(ctx, fake, branch)
    assert events[-1]["type"] == "done", events
    return u.id, events[-1]["message"]["id"]


# --- Trees and sending (Req 1, 2) -------------------------------------------------------------------


async def test_a_new_tree_has_an_empty_open_trunk_and_is_titled_from_the_first_message(ctx: Ctx) -> None:
    tid, trunk = new_tree(ctx)
    snap = snapshot(ctx, tid)
    assert snap.branches[trunk].kind is BranchKind.TRUNK and snap.chain(trunk) == ()  # Req 1.1
    messages.send_message(ctx, trunk, "  " + "x" * 80)
    with ctx.store.read() as c:
        tree = repo.get_tree(c, tid)
    assert tree is not None and tree.title == "x" * 60  # Req 1.3
    trees.rename_tree(ctx, tid, "My tree")
    with ctx.store.read() as c:
        assert repo.get_tree(c, tid).title == "My tree"  # type: ignore[union-attr]
    for bad in ("", "  ", "x" * 201):
        with pytest.raises(ValidationError) as e:
            trees.rename_tree(ctx, tid, bad)
        assert e.value.fields == ("title",)  # Req 1.4
    with pytest.raises(NotFound):
        trees.rename_tree(ctx, "nope", "t")


async def test_sending_validates_and_enforces_one_pending_message(ctx: Ctx, fake: FakeProvider) -> None:
    _, trunk = new_tree(ctx)
    for bad in ("", "   ", "x" * 100_001):
        before = counts(ctx)
        with pytest.raises(ValidationError) as e:
            messages.send_message(ctx, trunk, bad)
        assert e.value.fields == ("content",) and counts(ctx) == before  # Req 2.7: nothing persisted
    messages.send_message(ctx, trunk, "hello")
    with pytest.raises(Conflict):  # Req 2.9
        messages.send_message(ctx, trunk, "again")
    with pytest.raises(NotFound):
        messages.send_message(ctx, "missing", "hi")
    await reply(ctx, fake, trunk)
    messages.send_message(ctx, trunk, "now it is fine")


async def test_a_reply_is_persisted_with_its_manifest_and_blocks(ctx: Ctx, fake: FakeProvider) -> None:  # Req 2.2, 7.7
    tid, trunk = new_tree(ctx)
    u = messages.send_message(ctx, trunk, "what is a tree")
    prepared = messages.prepare_reply(ctx, trunk)
    events = await reply(ctx, fake, trunk)
    assert [e["type"] for e in events][0] == "delta" and events[-1]["type"] == "done"
    mid = events[-1]["message"]["id"]
    assert fake.requests[-1] == prepared.request  # exactly what the manifest describes
    with ctx.store.read() as c:
        manifest = repo.get_manifest(c, mid)
    assert manifest == prepared.manifest and [e.id for e in manifest.entries if isinstance(e, MessageEntry)] == [u.id]
    snap = snapshot(ctx, tid)
    m = snap.messages[mid]
    assert m.role is Role.ASSISTANT and m.model == "fake-model" and m.blocks_json and "fake-sig-" in m.blocks_json
    assert "".join(e["text"] for e in events if e["type"] == "delta") == m.content


async def test_a_failed_or_refused_reply_keeps_the_user_message_and_can_be_retried(
    ctx: Ctx, fake: FakeProvider
) -> None:
    tid, trunk = new_tree(ctx)
    messages.send_message(ctx, trunk, "hello")
    for outcome, category in (("fail", "provider_error"), ("refuse", "refused"), ("too_large", "context_too_large")):
        before = counts(ctx)
        fake.then(outcome)
        events = await reply(ctx, fake, trunk)
        assert events[-1]["type"] == "error" and events[-1]["error"] == category  # Req 2.3
        assert counts(ctx) == before
    assert len(snapshot(ctx, tid).chain(trunk)) == 1
    events = await reply(ctx, fake, trunk)  # asking again works
    assert events[-1]["type"] == "done"


async def test_a_reply_cut_off_at_the_output_limit_is_saved_and_marked(ctx: Ctx, fake: FakeProvider) -> None:  # Req 2.4
    _, trunk = new_tree(ctx)
    messages.send_message(ctx, trunk, "hello")
    fake.then("truncate")
    events = await reply(ctx, fake, trunk)
    assert events[-1]["type"] == "done" and events[-1]["message"]["cut_off"] is True


async def test_a_reply_cannot_be_requested_without_a_user_message_to_answer(ctx: Ctx, fake: FakeProvider) -> None:
    tid, trunk = new_tree(ctx)
    with pytest.raises(Conflict):
        messages.prepare_reply(ctx, trunk)  # empty
    _, a = await chat(ctx, fake, trunk, "q")
    with pytest.raises(Conflict):
        messages.prepare_reply(ctx, trunk)  # last message is the reply
    t = branches.spawn_tangent(ctx, a, 0, 4, snapshot(ctx, tid).messages[a].content[:4])
    with pytest.raises(Conflict):
        messages.prepare_reply(ctx, t.id)  # an empty tangent has nothing to answer yet


async def test_busy_branches_refuse_messages_and_replies(tmp_path: Path, fake: FakeProvider) -> None:  # Req 2.5
    busy: set[str] = set()
    ctx = make_ctx(tmp_path, busy.__contains__)
    _, trunk = new_tree(ctx)
    messages.send_message(ctx, trunk, "hello")
    busy.add(trunk)
    with pytest.raises(Busy):
        messages.send_message(ctx, trunk, "more")
    with pytest.raises(Busy):
        messages.prepare_reply(ctx, trunk)


# --- Tangents (Req 4, 7.3, 9) -----------------------------------------------------------------------


async def test_a_tangent_belongs_to_the_branch_that_owns_its_anchor(
    ctx: Ctx, fake: FakeProvider
) -> None:  # Req 4.4, 4.7
    tid, trunk = new_tree(ctx)
    _, a = await chat(ctx, fake, trunk, "tell me about caching")
    quote = snapshot(ctx, tid).messages[a].content[:10]
    t1 = branches.spawn_tangent(ctx, a, 0, 10, quote, "why")
    assert t1.parent_branch_id == trunk and t1.status is Status.PARKED and t1.fork_point_message_id == a
    messages.send_message(ctx, t1.id, "first tangent question")
    ev = await reply(ctx, fake, t1.id)
    inner = ev[-1]["message"]["id"]
    q2 = snapshot(ctx, tid).messages[inner].content[:6]
    # Spawned "from the trunk's view", but the selection lies in the tangent's reply: its parent is the tangent.
    t2 = branches.spawn_tangent(ctx, inner, 0, 6, q2, None, "anchor", Status.OPEN)
    assert t2.parent_branch_id == t1.id and t2.status is Status.OPEN and t2.intent is None


async def test_tangent_validation(ctx: Ctx, fake: FakeProvider) -> None:  # Req 4.3, 4.5
    tid, trunk = new_tree(ctx)
    _, a = await chat(ctx, fake, trunk, "q")
    text = snapshot(ctx, tid).messages[a].content
    before = counts(ctx)
    cases: list[tuple[dict[str, object], str]] = [
        ({"start": 0, "end": 4, "quoted_text": "nope"}, "anchor"),
        ({"start": 5, "end": 5, "quoted_text": ""}, "anchor"),
        ({"start": 0, "end": len(text) + 1, "quoted_text": text}, "anchor"),
        ({"start": 0, "end": 3, "quoted_text": text[:3], "intent": "x" * 201}, "intent"),
        ({"start": 0, "end": 3, "quoted_text": text[:3], "fork_at": "middle"}, "fork_point"),
        ({"start": 0, "end": 3, "quoted_text": text[:3], "status": Status.CLOSED}, "status"),
    ]
    for kwargs, field in cases:
        with pytest.raises(ValidationError) as e:
            branches.spawn_tangent(ctx, a, **kwargs)  # type: ignore[arg-type]
        assert e.value.fields == (field,)
    assert counts(ctx) == before
    with pytest.raises(NotFound):
        branches.spawn_tangent(ctx, "missing", 0, 1, "x")


async def test_framing_is_fixed_with_the_first_message_and_survives_a_label_edit(ctx: Ctx, fake: FakeProvider) -> None:
    tid, trunk = new_tree(ctx)
    _, a = await chat(ctx, fake, trunk, "q")
    text = snapshot(ctx, tid).messages[a].content
    t = branches.spawn_tangent(ctx, a, 0, 5, text[:5], "original label")
    assert snapshot(ctx, tid).branches[t.id].framing_text is None
    messages.send_message(ctx, t.id, "hello tangent")
    frozen = snapshot(ctx, tid).branches[t.id].framing_text
    assert frozen and "original label" in frozen and text[:5] in frozen  # Req 7.3
    branches.set_intent(ctx, t.id, "renamed")
    assert snapshot(ctx, tid).branches[t.id].framing_text == frozen
    assert snapshot(ctx, tid).branches[t.id].intent == "renamed"
    with pytest.raises(Conflict):
        branches.set_intent(ctx, trunk, "x")


async def test_the_fork_point_can_move_only_before_the_first_message(ctx: Ctx, fake: FakeProvider) -> None:  # Req 9
    tid, trunk = new_tree(ctx)
    _, a = await chat(ctx, fake, trunk, "q")
    _, a2 = await chat(ctx, fake, trunk, "q2")
    text = snapshot(ctx, tid).messages[a].content
    t = branches.spawn_tangent(ctx, a, 0, 5, text[:5])
    assert t.fork_point_message_id == a
    moved = branches.set_fork_point(ctx, t.id, "tip")
    assert moved.fork_point_message_id == a2  # the parent's current Tip
    assert branches.set_fork_point(ctx, t.id, "anchor").fork_point_message_id == a
    with pytest.raises(ValidationError):
        branches.set_fork_point(ctx, t.id, "middle")
    messages.send_message(ctx, t.id, "go")
    with pytest.raises(ValidationError) as e:
        branches.set_fork_point(ctx, t.id, "tip")
    assert e.value.fields == ("fork_point",)  # Req 9.3
    with pytest.raises(Conflict):
        branches.set_fork_point(ctx, trunk, "tip")


# --- Alternatives (Req 3) ---------------------------------------------------------------------------


async def test_editing_a_message_creates_an_alternative_and_changes_nothing_else(ctx: Ctx, fake: FakeProvider) -> None:
    tid, trunk = new_tree(ctx)
    u, a = await chat(ctx, fake, trunk, "original question")
    before = snapshot(ctx, tid)
    alt = messages.edit_message(ctx, u, "edited question")
    after = snapshot(ctx, tid)
    assert alt.kind is BranchKind.ALTERNATIVE and alt.parent_branch_id == trunk  # Req 3.2
    assert alt.anchor is not None and alt.anchor.message_id == u and alt.fork_point_message_id is None
    assert [after.messages[m].content for m in after.chain(alt.id)] == ["edited question"]
    assert all(after.messages[m] == before.messages[m] for m in before.messages)  # Req 3.1
    with pytest.raises(Conflict):
        messages.send_message(ctx, alt.id, "second message before reply")  # one pending message at a time (Req 2.9)
    events = await reply(ctx, fake, alt.id)
    assert events[-1]["type"] == "done"
    with pytest.raises(Conflict):
        messages.edit_message(ctx, a, "can't edit a reply")


async def test_regenerating_a_reply_creates_an_empty_alternative_that_gets_its_own_reply(
    ctx: Ctx, fake: FakeProvider
) -> None:
    tid, trunk = new_tree(ctx)
    u, a = await chat(ctx, fake, trunk, "question")
    alt = messages.regenerate_message(ctx, a)
    assert snapshot(ctx, tid).chain(alt.id) == () and alt.fork_point_message_id == u  # Req 3.3
    with pytest.raises(Conflict):
        messages.send_message(ctx, alt.id, "typing instead of regenerating")
    events = await reply(ctx, fake, alt.id)
    new_id = events[-1]["message"]["id"]
    snap = snapshot(ctx, tid)
    assert snap.messages[new_id].parent_message_id == u and snap.chain(trunk)[-1] == a
    with pytest.raises(Conflict):
        messages.regenerate_message(ctx, u)


async def test_an_alternative_of_a_tangents_first_message_keeps_its_framing(
    ctx: Ctx, fake: FakeProvider
) -> None:  # 3.5
    tid, trunk = new_tree(ctx)
    _, a = await chat(ctx, fake, trunk, "q")
    t = branches.spawn_tangent(ctx, a, 0, 4, snapshot(ctx, tid).messages[a].content[:4], "why")
    first = messages.send_message(ctx, t.id, "tangent question")
    alt = messages.edit_message(ctx, first.id, "better tangent question")
    prepared = messages.prepare_reply(ctx, alt.id)
    framing = [e for e in prepared.manifest.entries if isinstance(e, FramingEntry)]
    assert len(framing) == 1 and framing[0].branch_id == t.id


# --- Status (Req 10, 12.7) --------------------------------------------------------------------------


async def test_status_changes_follow_the_machine_and_are_recorded(ctx: Ctx, fake: FakeProvider) -> None:
    tid, trunk = new_tree(ctx)
    _, a = await chat(ctx, fake, trunk, "q")
    t = branches.spawn_tangent(ctx, a, 0, 4, snapshot(ctx, tid).messages[a].content[:4])
    assert branches.change_status(ctx, t.id, Action.RESUME).status is Status.OPEN
    assert branches.change_status(ctx, t.id, Action.PARK).status is Status.PARKED
    with pytest.raises(Conflict):
        branches.change_status(ctx, t.id, Action.PARK)
    with pytest.raises(Conflict):
        branches.change_status(ctx, trunk, Action.PARK)
    with pytest.raises(ValueError):
        branches.change_status(ctx, t.id, Action.CLOSE)
    with ctx.store.read() as c:
        events = [
            (r[0], r[1])
            for r in c.execute(
                "SELECT from_status, to_status FROM status_events WHERE branch_id = ? ORDER BY id", (t.id,)
            )
        ]
    assert events == [(None, "parked"), ("parked", "open"), ("open", "parked")]  # Req 16.4


async def test_sending_in_a_parked_branch_opens_it(ctx: Ctx, fake: FakeProvider) -> None:  # Req 2.8
    tid, trunk = new_tree(ctx)
    _, a = await chat(ctx, fake, trunk, "q")
    t = branches.spawn_tangent(ctx, a, 0, 4, snapshot(ctx, tid).messages[a].content[:4])
    messages.send_message(ctx, t.id, "hi")
    assert snapshot(ctx, tid).branches[t.id].status is Status.OPEN


# --- Closing and merging (Req 12, 13) ---------------------------------------------------------------


async def two_deep(ctx: Ctx, fake: FakeProvider):  # noqa: ANN201
    tid, trunk = new_tree(ctx)
    _, a = await chat(ctx, fake, trunk, "tell me about caching")
    t1 = branches.spawn_tangent(ctx, a, 0, 10, snapshot(ctx, tid).messages[a].content[:10], "why")
    _, a1 = await chat(ctx, fake, t1.id, "first tangent question")
    t2 = branches.spawn_tangent(ctx, a1, 0, 6, snapshot(ctx, tid).messages[a1].content[:6], "deeper")
    await chat(ctx, fake, t2.id, "second tangent question")
    return tid, trunk, a, t1.id, a1, t2.id


async def test_merging_appends_one_note_to_the_parent_and_rewrites_nothing(ctx: Ctx, fake: FakeProvider) -> None:
    tid, trunk, _, t1, _, _ = await two_deep(ctx, fake)
    before = snapshot(ctx, tid)
    result = closing.close_branch(ctx, t1, Outcome.MERGED, "  The cache keys on exact prefix bytes.  ")
    after = snapshot(ctx, tid)
    assert result.note is not None and result.note.role is Role.NOTE and result.note.source_branch_id == t1
    assert after.chain(trunk)[-1] == result.note.id and len(after.chain(trunk)) == len(before.chain(trunk)) + 1  # 13.1
    assert all(after.messages[m] == before.messages[m] for m in before.messages)  # Req 13.6
    assert 'from_branch="why"' in result.note.content and "The cache keys on exact prefix bytes." in result.note.content
    assert after.branches[t1].status is Status.CLOSED
    with ctx.store.read() as c:
        (row,) = repo.closings_for(c, t1)
    assert (
        row.outcome is Outcome.MERGED and row.note_message_id == result.note.id and row.merge_target_branch_id == trunk
    )
    with pytest.raises(Conflict):
        messages.send_message(ctx, t1, "into a closed branch")  # Req 12.8
    with pytest.raises(Conflict):
        closing.close_branch(ctx, t1, Outcome.KEPT, "again")
    # The Note now reaches later replies in the target.
    messages.send_message(ctx, trunk, "what did we learn")
    prepared = messages.prepare_reply(ctx, trunk)
    assert result.note.id in {e.id for e in prepared.manifest.entries if isinstance(e, MessageEntry)}


async def test_a_note_does_not_reach_a_tangent_anchored_above_it_but_does_reach_a_tip_fork(
    ctx: Ctx, fake: FakeProvider
) -> None:
    tid, trunk, a, t1, _, _ = await two_deep(ctx, fake)
    note = closing.close_branch(ctx, t1, Outcome.MERGED, "found it").note
    assert note is not None
    text = snapshot(ctx, tid).messages[a].content
    above = branches.spawn_tangent(ctx, a, 0, 4, text[:4])
    tip = branches.spawn_tangent(ctx, a, 0, 4, text[:4], fork_at="tip")
    snap = snapshot(ctx, tid)
    assert note.id not in {
        e.id for e in context.inherited_prefix(snap, above.id) if isinstance(e, MessageEntry)
    }  # 13.6
    assert note.id in {e.id for e in context.inherited_prefix(snap, tip.id) if isinstance(e, MessageEntry)}


async def test_merge_targets_and_other_close_rules(ctx: Ctx, fake: FakeProvider) -> None:
    tid, trunk, _, t1, _, t2 = await two_deep(ctx, fake)
    before = counts(ctx)
    cases: list[tuple[dict[str, object], type[Exception], str]] = [
        ({"outcome": Outcome.MERGED, "conclusion": ""}, ValidationError, "conclusion"),  # Req 12.2
        ({"outcome": Outcome.KEPT, "conclusion": "x" * 2001}, ValidationError, "conclusion"),  # Req 12.3
        ({"outcome": Outcome.MERGED, "conclusion": "c", "merge_target": t2}, ValidationError, "merge_target"),
        ({"outcome": Outcome.KEPT, "conclusion": "c", "merge_target": trunk}, ValidationError, "merge_target"),
    ]
    for kwargs, exc, field in cases:
        with pytest.raises(exc) as e:
            closing.close_branch(ctx, t2, **kwargs)  # type: ignore[arg-type]
        assert getattr(e.value, "fields", ()) == (field,)
    assert counts(ctx) == before
    # Any open ancestor is a valid target (Req 13.3): merge the grandchild straight into the trunk.
    result = closing.close_branch(ctx, t2, Outcome.MERGED, "skip a level", merge_target=trunk)
    assert result.note is not None and result.note.branch_id == trunk
    with pytest.raises(Conflict):
        closing.close_branch(ctx, trunk, Outcome.KEPT, "x")  # Req 12.9
    with pytest.raises(Conflict):
        closing.close_branch(ctx, t2, Outcome.ABANDONED)  # already closed
    # A closed ancestor is no longer a target.
    closing.close_branch(ctx, t1, Outcome.KEPT, "kept without merging")
    assert snapshot(ctx, tid).branches[t1].status is Status.CLOSED
    assert len(snapshot(ctx, tid).chain(trunk)) == 3  # one question, one reply, one note (kept added none)


async def test_abandoned_needs_no_conclusion_and_alternatives_cannot_merge(ctx: Ctx, fake: FakeProvider) -> None:
    tid, trunk = new_tree(ctx)
    u, a = await chat(ctx, fake, trunk, "q")
    alt = messages.regenerate_message(ctx, a)
    with pytest.raises(ValidationError) as e:
        closing.close_branch(ctx, alt.id, Outcome.MERGED, "c")
    assert e.value.fields == ("outcome",)  # Req 12.9
    closing.close_branch(ctx, alt.id, Outcome.ABANDONED)
    t = branches.spawn_tangent(ctx, a, 0, 3, snapshot(ctx, tid).messages[a].content[:3])
    closing.close_branch(ctx, t.id, Outcome.ABANDONED, None)
    with ctx.store.read() as c:
        assert repo.closings_for(c, t.id)[0].conclusion is None
    assert u


async def test_closing_can_abandon_descendants_in_the_same_action(ctx: Ctx, fake: FakeProvider) -> None:  # Req 12.6
    tid, trunk, _, t1, _, t2 = await two_deep(ctx, fake)
    result = closing.close_branch(ctx, t1, Outcome.KEPT, "done", abandon_descendants=True)
    snap = snapshot(ctx, tid)
    assert result.abandoned == (t2,) and snap.branches[t2].status is Status.CLOSED
    with ctx.store.read() as c:
        assert repo.closings_for(c, t2)[0].outcome is Outcome.ABANDONED
    # Without the flag, descendants stay as they are.
    tid2, trunk2, _, u1, _, u2 = await two_deep(ctx, fake)
    closing.close_branch(ctx, u1, Outcome.KEPT, "done")
    assert snapshot(ctx, tid2).branches[u2].status is not Status.CLOSED and trunk2


async def test_reopening_keeps_the_earlier_record_and_a_later_close_adds_another(ctx: Ctx, fake: FakeProvider) -> None:
    tid, trunk, _, t1, _, _ = await two_deep(ctx, fake)
    closing.close_branch(ctx, t1, Outcome.KEPT, "first conclusion")
    assert branches.change_status(ctx, t1, Action.REOPEN).status is Status.OPEN  # Req 12.7
    await chat(ctx, fake, t1, "one more thing")
    closing.close_branch(ctx, t1, Outcome.MERGED, "second conclusion")
    with ctx.store.read() as c:
        rows = repo.closings_for(c, t1)
    assert [r.conclusion for r in rows] == ["first conclusion", "second conclusion"]


async def test_a_failed_merge_writes_nothing(ctx: Ctx, fake: FakeProvider) -> None:  # Req 13.1, 16.5
    tid, trunk, _, t1, _, _ = await two_deep(ctx, fake)
    messages.send_message(ctx, trunk, "an unanswered question")  # the merge target now awaits a reply
    before = counts(ctx)
    with pytest.raises(Conflict):
        closing.close_branch(ctx, t1, Outcome.MERGED, "c")  # Req 13.5 / 2.9
    assert counts(ctx) == before and snapshot(ctx, tid).branches[t1].status is not Status.CLOSED


async def test_busy_branches_cannot_be_closed_or_merged_into(tmp_path: Path, fake: FakeProvider) -> None:  # Req 13.5
    busy: set[str] = set()
    ctx = make_ctx(tmp_path, busy.__contains__)
    tid, trunk, _, t1, _, t2 = await two_deep(ctx, fake)
    busy.add(trunk)
    with pytest.raises(Busy):
        closing.close_branch(ctx, t1, Outcome.MERGED, "c")
    busy.clear()
    busy.add(t1)
    with pytest.raises(Busy):
        closing.close_branch(ctx, t1, Outcome.KEPT, "c")
    with pytest.raises(Busy):
        closing.close_branch(ctx, t1, Outcome.KEPT, "c", abandon_descendants=True)
    busy.clear()
    busy.add(t2)
    with pytest.raises(Busy):
        closing.close_branch(ctx, t1, Outcome.KEPT, "c", abandon_descendants=True)
    assert tid


# --- Generated text (Req 11, 12.1) ------------------------------------------------------------------


async def test_a_generated_intent_is_stored_but_never_reaches_a_context(ctx: Ctx, fake: FakeProvider) -> None:
    tid, trunk = new_tree(ctx)
    _, a = await chat(ctx, fake, trunk, "q")
    text = snapshot(ctx, tid).messages[a].content
    plain = branches.spawn_tangent(ctx, a, 0, 5, text[:5])
    labelled = branches.spawn_tangent(ctx, a, 0, 5, text[:5], "my own label")
    generated = await generate_intent(ctx, fake, plain.id)
    assert generated and generated.startswith("Fake summary")  # Req 11.1
    assert await generate_intent(ctx, fake, labelled.id) is None  # an Intent exists: nothing to generate
    with ctx.store.read() as c:
        assert repo.latest_generated(c, plain.id, "intent") == generated
    messages.send_message(ctx, plain.id, "go")
    prepared = messages.prepare_reply(ctx, plain.id)
    assert generated not in str(prepared.request)  # Req 11.5
    assert "did not state an intent" in str(prepared.request)
    # It becomes the Note label when the Branch is merged (Req 13.2).
    await reply(ctx, fake, plain.id)
    note = closing.close_branch(ctx, plain.id, Outcome.MERGED, "c").note
    assert note is not None and generated in note.content


async def test_generated_text_failures_are_silent(ctx: Ctx, fake: FakeProvider) -> None:  # Req 11.3
    tid, trunk = new_tree(ctx)
    _, a = await chat(ctx, fake, trunk, "q")
    t = branches.spawn_tangent(ctx, a, 0, 3, snapshot(ctx, tid).messages[a].content[:3])
    fake.available = False
    assert await generate_intent(ctx, fake, t.id) is None and await generate_standing(ctx, fake, t.id) is None
    with ctx.store.read() as c:
        assert repo.latest_generated(c, t.id, "intent") is None


async def test_standing_summary_needs_a_reply_and_the_draft_is_not_stored(ctx: Ctx, fake: FakeProvider) -> None:
    tid, trunk = new_tree(ctx)
    _, a = await chat(ctx, fake, trunk, "q")
    t = branches.spawn_tangent(ctx, a, 0, 3, snapshot(ctx, tid).messages[a].content[:3], "i")
    assert await generate_standing(ctx, fake, t.id) is None  # nothing to summarise yet (Req 11.2)
    await chat(ctx, fake, t.id, "tangent question")
    assert (await generate_standing(ctx, fake, t.id) or "").startswith("Fake summary")
    before = counts(ctx)
    draft = await draft_conclusion(ctx, fake, t.id)
    assert draft and counts(ctx) == before  # Req 12.1: drafts are not stored
    assert "tangent question" in fake.completions[-1][1]
