"""Branch_Summaries in the domain: the source window, the frozen prompt and cleaning (Req 9, Property 9)."""

from __future__ import annotations

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from treechat.domain import rules, summaries
from treechat.domain.model import TreeSnapshot

from .helpers import reply, user
from .test_domain import trees


@settings(max_examples=300)
@given(trees)
def test_the_source_is_the_last_five_of_the_path_to_the_branch_end(snap: TreeSnapshot) -> None:  # Property 9
    for b in rules.branches(snap):
        src = summaries.summary_source(snap, b)
        full = rules.path(snap, b.message_ids[-1])
        assert src == full[-5:]
        assert len(src) == min(5, len(full))
        assert src[-1] == b.message_ids[-1]  # the newest Message is the Branch's own end


@settings(max_examples=200)
@given(trees)
def test_the_prompt_is_byte_identical_every_time(snap: TreeSnapshot) -> None:  # Property 9, Req 9.2
    for b in rules.branches(snap):
        msgs = [snap.messages[i] for i in summaries.summary_source(snap, b)]
        assert summaries.summary_prompt(msgs) == summaries.summary_prompt(list(msgs))


@settings(max_examples=200)
@given(trees)
def test_every_branch_start_is_a_user_message(snap: TreeSnapshot) -> None:  # Req 9.1, the Store's trigger
    for mid in summaries.branch_starts(snap):
        assert snap.messages[mid].role.value == "user"


def test_the_newest_message_is_marked_and_long_messages_are_clipped() -> None:  # Req 9.2
    msgs = [
        user("u1", "T", None, "How do caches work?", "t1"),
        reply("a1", "T", "u1", "y" * 5000, "t2"),
        user("u2", "T", "a1", "And what about ETags?", "t3"),
    ]
    system, prompt = summaries.summary_prompt(msgs)
    assert system == summaries.SUMMARY_SYSTEM_V1
    assert '<newest role="user">\nAnd what about ETags?\n</newest>' in prompt
    assert prompt.count("<newest") == 1
    assert '<message role="user">\nHow do caches work?\n</message>' in prompt
    assert "y" * 4000 in prompt and "y" * 4001 not in prompt
    assert prompt.index("How do caches") < prompt.index("yyyy") < prompt.index("ETags")  # oldest first
    assert "weighted towards the newest" in prompt


def test_a_new_fork_and_its_older_sibling_are_named_from_their_own_ends() -> None:  # Req 9.1, owner's answer C
    msgs = [user("r", "T", None, "q0", "t0"), reply("a", "T", "r", "x", "t1")]
    for i in range(1, 5):  # a straight thread r, a, u1, a1, ... u4, a4
        msgs.append(user(f"u{i}", "T", "a" if i == 1 else f"a{i - 1}", f"q{i}", f"t{2 * i}"))
        msgs.append(reply(f"a{i}", "T", f"u{i}", "x", f"t{2 * i + 1}"))
    msgs.append(user("new", "T", "a", "a different question", "t99"))  # fork at a
    snap = TreeSnapshot.build(msgs)
    by_start = {b.id: b for b in rules.branches(snap)}
    assert summaries.summary_source(snap, by_start["new"]) == ("r", "a", "new")  # its first question and what led there
    assert summaries.summary_source(snap, by_start["u1"]) == (
        "a2",
        "u3",
        "a3",
        "u4",
        "a4",
    )  # the split-off: its latest five
    assert summaries.summary_source(snap, by_start["r"]) == ("r", "a")


@pytest.mark.parametrize(
    ("raw", "clean"),
    [
        ('"HTTP caching and freshness rules."', "HTTP caching and freshness rules"),
        ("**ETag revalidation explained**\n", "ETag revalidation explained"),
        ("\n\n  Vary header and encodings  \nsecond line", "Vary header and encodings"),
        ("one two three four five six seven eight nine ten", "one two three four five six seven eight"),
        ("x" * 80, "x" * 60),
        (
            "abcdefghijklmnopqrstuvwxyz, abcdefghijklmnopqrstuvwxyz, abcdefghij",
            "abcdefghijklmnopqrstuvwxyz, abcdefghijklmnopqrstuvwxyz",
        ),  # cut at 60 lands after a comma
        ("'…'", "…"),
        ("", None),
        ('  "  ".  ', None),
        ("...", None),
    ],
)
def test_clean_summary_examples(raw: str, clean: str | None) -> None:  # Req 9.5
    assert summaries.clean_summary(raw) == clean


@given(st.text(max_size=300))
def test_a_cleaned_summary_always_fits(text: str) -> None:  # Req 9.3, 9.5: the Store's limits
    out = summaries.clean_summary(text)
    if out is not None:
        assert 1 <= len(out) <= 60
        assert len(out.split()) <= 8
        assert "\n" not in out
        assert out == out.strip()
        assert out[-1] not in ".!?:;,\"'"
