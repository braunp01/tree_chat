"""Unit tests for validation, the Status machine and tree navigation (Req 1.4, 2.7, 4.3, 4.5, 10.1, 12, 13.3)."""

from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from treechat.domain import rules
from treechat.domain.errors import Conflict, ValidationError
from treechat.domain.model import Action, BranchKind, Outcome, Role, Status
from treechat.domain.queue import QueueOrder, queue

from .builder import Builder


@pytest.mark.parametrize("n,ok", [(0, False), (1, True), (200, True), (201, False)])
def test_title_boundaries(n: int, ok: bool) -> None:  # Req 1.4
    if ok:
        assert rules.clean_title("x" * n) == "x" * n
    else:
        with pytest.raises(ValidationError) as e:
            rules.clean_title("x" * n)
        assert e.value.fields == ("title",)


def test_title_is_trimmed_before_checking() -> None:
    assert rules.clean_title("  hi  ") == "hi"
    with pytest.raises(ValidationError):
        rules.clean_title("   ")


@pytest.mark.parametrize("n,ok", [(0, False), (1, True), (100_000, True), (100_001, False)])
def test_content_boundaries(n: int, ok: bool) -> None:  # Req 2.7
    if ok:
        rules.clean_content("x" * n)
    else:
        with pytest.raises(ValidationError) as e:
            rules.clean_content("x" * n)
        assert e.value.fields == ("content",)


def test_whitespace_only_content_rejected() -> None:
    with pytest.raises(ValidationError):
        rules.clean_content(" \n\t ")


@pytest.mark.parametrize("n,ok", [(199, True), (200, True), (201, False)])
def test_intent_boundaries(n: int, ok: bool) -> None:  # Req 4.3
    if ok:
        assert rules.clean_intent("x" * n) == "x" * n
    else:
        with pytest.raises(ValidationError) as e:
            rules.clean_intent("x" * n)
        assert e.value.fields == ("intent",)


def test_empty_intent_means_none() -> None:
    assert rules.clean_intent("") is None
    assert rules.clean_intent("   ") is None
    assert rules.clean_intent(None) is None


@pytest.mark.parametrize(
    "outcome,conclusion,ok",
    [
        (Outcome.MERGED, "", False),
        (Outcome.MERGED, "  ", False),
        (Outcome.KEPT, None, False),
        (Outcome.ABANDONED, None, True),
        (Outcome.ABANDONED, "", True),
        (Outcome.MERGED, "x" * 2000, True),
        (Outcome.MERGED, "x" * 2001, False),
        (Outcome.ABANDONED, "x" * 2001, False),
    ],
)
def test_conclusion_rules(outcome: Outcome, conclusion: str | None, ok: bool) -> None:  # Req 12.2-12.3
    if ok:
        rules.clean_conclusion(outcome, conclusion)
    else:
        with pytest.raises(ValidationError) as e:
            rules.clean_conclusion(outcome, conclusion)
        assert e.value.fields == ("conclusion",)


@pytest.mark.parametrize(
    "start,end,quote,ok",
    [
        (0, 5, "hello", True),
        (0, 11, "hello world", True),
        (6, 11, "world", True),
        (0, 12, "hello world!", False),  # end beyond len
        (5, 5, "", False),  # start not less than end
        (6, 5, "", False),
        (-1, 3, "hel", False),
        (0, 5, "Hello", False),  # wrong text
    ],
)
def test_anchor_boundaries(start: int, end: int, quote: str, ok: bool) -> None:  # Req 4.5
    assert (rules.anchor_error("hello world", start, end, quote) is None) is ok


def test_anchor_offsets_count_code_points() -> None:
    text = "a😀b"  # three code points, four UTF-16 units
    assert rules.anchor_error(text, 1, 2, "😀") is None
    assert rules.anchor_error(text, 0, 3, text) is None
    assert rules.anchor_error(text, 0, 4, text) is not None


@given(st.text(max_size=30), st.integers(-3, 35), st.integers(-3, 35))
def test_property_10_anchor_validation_is_exact(content: str, start: int, end: int) -> None:
    """Property 10 (Req 4.5): accepted iff 0 <= start < end <= len and the code-point slice equals the quote."""
    valid = 0 <= start < end <= len(content)
    quote = content[start:end] if valid else content[:3]
    assert (rules.anchor_error(content, start, end, quote) is None) is valid
    if valid:
        assert rules.anchor_error(content, start, end, quote + "x") is not None


def test_status_machine_allows_exactly_the_listed_transitions() -> None:  # Req 10.1, 12.7-12.9
    allowed = {
        (Status.OPEN, Action.PARK, Status.PARKED),
        (Status.PARKED, Action.RESUME, Status.OPEN),
        (Status.OPEN, Action.CLOSE, Status.CLOSED),
        (Status.PARKED, Action.CLOSE, Status.CLOSED),
        (Status.CLOSED, Action.REOPEN, Status.OPEN),
        (Status.OPEN, Action.SEND, Status.OPEN),
        (Status.PARKED, Action.SEND, Status.OPEN),
    }
    for s in Status:
        for a in Action:
            hit = [t for (s0, a0, t) in allowed if (s0, a0) == (s, a)]
            if hit:
                assert rules.transition(s, a, BranchKind.TANGENT) is hit[0]
            else:
                with pytest.raises(Conflict):
                    rules.transition(s, a, BranchKind.TANGENT)


def test_trunk_only_ever_sends() -> None:
    assert rules.transition(Status.OPEN, Action.SEND, BranchKind.TRUNK) is Status.OPEN
    for a in (Action.PARK, Action.CLOSE, Action.RESUME, Action.REOPEN):
        with pytest.raises(Conflict):
            rules.transition(Status.OPEN, a, BranchKind.TRUNK)


def test_alternative_cannot_be_merged() -> None:  # Req 12.9
    with pytest.raises(ValidationError) as e:
        rules.check_outcome(BranchKind.ALTERNATIVE, Outcome.MERGED)
    assert e.value.fields == ("outcome",)
    rules.check_outcome(BranchKind.ALTERNATIVE, Outcome.KEPT)
    rules.check_outcome(BranchKind.TANGENT, Outcome.MERGED)


def _three_deep() -> tuple[Builder, str, str, str]:
    b = Builder()
    m = b.add(b.trunk, Role.USER, "one two three")
    t1 = b.spawn(m, 0, 3)
    m1 = b.add(t1, Role.USER, "inner question")
    t2 = b.spawn(m1, 0, 5)
    return b, t1, t2, m


def test_merge_targets_are_non_closed_ancestors_nearest_first() -> None:  # Req 13.3
    b, t1, t2, _ = _three_deep()
    assert rules.merge_targets(b.snapshot(), t2) == (t1, b.trunk)
    b.set_status(t1, Status.CLOSED)
    assert rules.merge_targets(b.snapshot(), t2) == (b.trunk,)
    assert rules.merge_targets(b.snapshot(), b.trunk) == ()


def test_navigation_helpers() -> None:
    b, t1, t2, m = _three_deep()
    snap = b.snapshot()
    assert rules.ancestors(snap, t2) == (t1, b.trunk)
    assert rules.descendants(snap, b.trunk) == (t1, t2)
    assert rules.depth(snap, t2) == 2
    assert rules.conversation_position(snap, m) == 0
    first = snap.chain(t1)[0]
    assert rules.conversation_position(snap, first) == 1  # one Message (the fork point) precedes it


def test_depth_has_no_cap() -> None:  # Req 4.7
    b = Builder()
    cur = b.trunk
    for _ in range(300):
        m = b.add(cur, Role.USER, "hello there")
        cur = b.spawn(m, 0, 5)
    assert rules.depth(b.snapshot(), cur) == 300


def test_parent_messages_since_fork_counts_only_later_messages() -> None:  # Req 10.5
    b = Builder()
    m1 = b.add(b.trunk, Role.USER, "alpha beta")
    t = b.spawn(m1, 0, 5)
    assert rules.parent_messages_since_fork(b.snapshot(), t) == 0
    b.add(b.trunk, Role.ASSISTANT, "reply")
    b.add(b.trunk, Role.USER, "more")
    assert rules.parent_messages_since_fork(b.snapshot(), t) == 2


def test_queue_orders_and_lists_only_parked() -> None:  # Req 10.2, 10.4
    b = Builder()
    m = b.add(b.trunk, Role.USER, "alpha beta gamma delta")
    first = b.spawn(m, 0, 5)
    second = b.spawn(m, 6, 10)
    third = b.spawn(m, 11, 16)
    b.set_status(second, Status.OPEN)
    snap = b.snapshot()
    assert [e.branch_id for e in queue(snap, QueueOrder.OLDEST)] == [first, third]
    assert [e.branch_id for e in queue(snap, QueueOrder.NEWEST)] == [third, first]
    assert [e.branch_id for e in queue(snap, QueueOrder.PARENT)] == [first, third]
