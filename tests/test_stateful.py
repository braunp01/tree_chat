"""Random sequences of every operation against a real store and the fake provider.

Checks Properties 1, 2, 6, 7, 8, 9, 11 and 12 after every step (design.md, Correctness Properties). Runs entirely
offline: the fake provider answers, so this test costs no AI credits (Req 17.5).
"""

from __future__ import annotations

import asyncio
import os
import tempfile
from typing import Any

from hypothesis import HealthCheck, settings
from hypothesis import strategies as st
from hypothesis.stateful import RuleBasedStateMachine, invariant, precondition, rule

from treechat.domain import context, render, rules
from treechat.domain.errors import Conflict, ValidationError
from treechat.domain.model import (
    Action,
    BranchKind,
    FramingEntry,
    MessageEntry,
    Outcome,
    Role,
    Status,
    TreeSnapshot,
)
from treechat.jobs.replies import generate_intent, generate_standing
from treechat.provider.fake import FakeProvider, check_request_shape
from treechat.services import branches, closing, messages, trees
from treechat.services.ctx import Ctx
from treechat.services.messages import prepare_reply
from treechat.store import repo
from treechat.store.db import Store

from .svc_helpers import SETTINGS, counting_env, counts, reply

ALLOWED = {
    (None, "open"),
    (None, "parked"),
    ("parked", "open"),
    ("open", "parked"),
    ("open", "closed"),
    ("parked", "closed"),
    ("closed", "open"),
}


class TreeMachine(RuleBasedStateMachine):
    def __init__(self) -> None:
        super().__init__()
        self.tmp = tempfile.TemporaryDirectory()
        self.ctx = Ctx(Store(f"{self.tmp.name}/m.sqlite3"), counting_env(), SETTINGS)
        self.fake = FakeProvider()
        self.tree_id, self.trunk = trees.create_tree(self.ctx)
        self.seen_messages: dict[str, Any] = {}
        self.seen_manifests: dict[str, str] = {}
        self.seen_branch_facts: dict[str, tuple[Any, ...]] = {}
        self.seen_closings: list[Any] = []
        self.seen_contexts: dict[str, tuple[Any, ...]] = {}
        self.seen_prefix: dict[str, tuple[Any, ...]] = {}
        self.closed_len: dict[str, int] = {}

    def teardown(self) -> None:
        self.tmp.cleanup()

    # -- helpers ---------------------------------------------------------------------------------
    def snap(self) -> TreeSnapshot:
        with self.ctx.store.read() as c:
            return repo.load_snapshot(c, self.tree_id)

    def last_role(self, snap: TreeSnapshot, bid: str) -> Role | None:
        chain = snap.chain(bid)
        return snap.messages[chain[-1]].role if chain else None

    def sendable(self) -> list[str]:
        s = self.snap()
        return sorted(
            b.id
            for b in s.branches.values()
            if b.status is not Status.CLOSED
            and self.last_role(s, b.id) is not Role.USER
            and not (b.kind is BranchKind.ALTERNATIVE and not s.chain(b.id))
        )

    def unsendable(self) -> list[str]:
        s = self.snap()
        return sorted(
            b.id
            for b in s.branches.values()
            if b.status is Status.CLOSED
            or self.last_role(s, b.id) is Role.USER
            or (b.kind is BranchKind.ALTERNATIVE and not s.chain(b.id))
        )

    def repliable(self) -> list[str]:
        s = self.snap()
        out = []
        for b in s.branches.values():
            if b.status is Status.CLOSED:
                continue
            chain = s.chain(b.id)
            if not chain and b.kind is not BranchKind.ALTERNATIVE:
                continue
            tip = rules.tip(s, b.id)
            if tip is not None and s.messages[tip].role is Role.USER:
                out.append(b.id)
        return sorted(out)

    # -- rules -----------------------------------------------------------------------------------
    @precondition(lambda self: bool(self.sendable()))
    @rule(data=st.data(), text=st.text(alphabet="abcdef ghij😀é", min_size=1, max_size=60).filter(lambda t: t.strip()))
    def send(self, data: st.DataObject, text: str) -> None:
        bid = data.draw(st.sampled_from(self.sendable()))
        before = self.snap()
        m = messages.send_message(self.ctx, bid, text)
        after = self.snap()
        assert after.chain(bid)[-1] == m.id and len(after.messages) == len(before.messages) + 1
        assert after.branches[bid].status is not Status.CLOSED

    @precondition(lambda self: bool(self.unsendable()))
    @rule(data=st.data())
    def send_refused(self, data: st.DataObject) -> None:
        """Req 2.9, 12.8, 3.3: refused sends change nothing (Property 11)."""
        bid = data.draw(st.sampled_from(self.unsendable()))
        before = counts(self.ctx)
        try:
            messages.send_message(self.ctx, bid, "should not be stored")
        except Conflict:
            pass
        else:
            raise AssertionError("send into an unsendable branch succeeded")
        assert counts(self.ctx) == before

    @precondition(lambda self: bool(self.repliable()))
    @rule(
        data=st.data(),
        outcome=st.sampled_from(["ok", "ok", "ok", "ok", "fail", "refuse", "truncate", "fallback"]),
    )
    def reply(self, data: st.DataObject, outcome: str) -> None:
        bid = data.draw(st.sampled_from(self.repliable()))
        before = counts(self.ctx)
        prepared = prepare_reply(self.ctx, bid)
        self.fake.then(outcome)
        events = asyncio.run(reply(self.ctx, self.fake, bid))
        if outcome in ("fail", "refuse"):
            assert events[-1]["type"] == "error" and counts(self.ctx) == before  # Property 11
        else:
            assert events[-1]["type"] == "done", events[-1]  # also proves the request met every API rule
            assert self.fake.requests[-1] == prepared.request
            assert counts(self.ctx)["messages"] == before["messages"] + 1

    @rule(data=st.data())
    def spawn(self, data: st.DataObject) -> None:
        s = self.snap()
        if not s.messages:
            return
        # Favour messages inside tangents, so trees grow deep enough to exercise merging past the parent.
        inner = sorted(m.id for m in s.messages.values() if m.branch_id != self.trunk)
        pool = inner if inner and data.draw(st.integers(0, 2)) else sorted(s.messages)
        m = s.messages[data.draw(st.sampled_from(pool))]
        n = len(m.content)
        start = data.draw(st.integers(0, n - 1))
        end = data.draw(st.integers(start + 1, n))
        before = len(s.branches)
        b = branches.spawn_tangent(
            self.ctx,
            m.id,
            start,
            end,
            m.content[start:end],
            data.draw(st.sampled_from([None, "", "why", "x" * 200])),
            data.draw(st.sampled_from(["anchor", "tip"])),
            data.draw(st.sampled_from([Status.PARKED, Status.OPEN])),
        )
        after = self.snap()
        assert len(after.branches) == before + 1 and b.parent_branch_id == m.branch_id  # Req 4.4

    @rule(data=st.data())
    def grow_deeper(self, data: st.DataObject) -> None:
        """Spawn a tangent from a message of a branch (preferably an inner one), send in it and get its reply, so that
        trees get deep enough to exercise merges past the parent and closing with descendants."""
        s = self.snap()
        live = [b.id for b in s.branches.values() if b.status is not Status.CLOSED and s.chain(b.id)]
        inner = [b for b in live if b != self.trunk]
        pool = inner if inner and data.draw(st.integers(0, 3)) else live
        if not pool:
            return
        bid = data.draw(st.sampled_from(sorted(pool)))
        m = s.messages[data.draw(st.sampled_from(list(s.chain(bid))))]
        end = data.draw(st.integers(1, len(m.content)))
        t = branches.spawn_tangent(self.ctx, m.id, 0, end, m.content[:end], "deeper", "anchor", Status.OPEN)
        messages.send_message(self.ctx, t.id, "a question inside the tangent")
        events = asyncio.run(reply(self.ctx, self.fake, t.id))
        assert events[-1]["type"] == "done", events[-1]

    @rule(data=st.data())
    def spawn_bad_anchor(self, data: st.DataObject) -> None:
        s = self.snap()
        if not s.messages:
            return
        m = s.messages[data.draw(st.sampled_from(sorted(s.messages)))]
        before = counts(self.ctx)
        try:
            branches.spawn_tangent(self.ctx, m.id, 0, len(m.content) + 1, m.content)
        except ValidationError:
            pass
        else:
            raise AssertionError("an anchor past the end was accepted")
        assert counts(self.ctx) == before

    @rule(data=st.data())
    def edit_or_regenerate(self, data: st.DataObject) -> None:
        s = self.snap()
        users = sorted(m.id for m in s.messages.values() if m.role is Role.USER)
        replies = sorted(m.id for m in s.messages.values() if m.role is Role.ASSISTANT)
        if users and (not replies or data.draw(st.booleans())):
            alt = messages.edit_message(self.ctx, data.draw(st.sampled_from(users)), "an edited message")
            assert alt.kind is BranchKind.ALTERNATIVE and len(self.snap().chain(alt.id)) == 1
        elif replies:
            alt = messages.regenerate_message(self.ctx, data.draw(st.sampled_from(replies)))
            assert alt.kind is BranchKind.ALTERNATIVE and self.snap().chain(alt.id) == ()

    @rule(data=st.data(), action=st.sampled_from([Action.PARK, Action.RESUME, Action.REOPEN]))
    def change_status(self, data: st.DataObject, action: Action) -> None:
        s = self.snap()
        bid = data.draw(st.sampled_from(sorted(s.branches)))
        b = s.branches[bid]
        try:
            expected = rules.transition(b.status, action, b.kind)
        except Conflict:
            before = counts(self.ctx)
            try:
                branches.change_status(self.ctx, bid, action)
            except Conflict:
                assert counts(self.ctx) == before
                return
            raise AssertionError("an illegal transition was accepted") from None
        assert branches.change_status(self.ctx, bid, action).status is expected

    @rule(data=st.data())
    def move_fork_or_label(self, data: st.DataObject) -> None:
        s = self.snap()
        tangents = sorted(b.id for b in s.branches.values() if b.kind is BranchKind.TANGENT)
        if not tangents:
            return
        bid = data.draw(st.sampled_from(tangents))
        if data.draw(st.booleans()):
            branches.set_intent(self.ctx, bid, data.draw(st.sampled_from([None, "relabelled", "x" * 200])))
        elif s.chain(bid):
            try:
                branches.set_fork_point(self.ctx, bid, "tip")
            except ValidationError:
                pass
            else:
                raise AssertionError("fork point moved after the first message")  # Req 9.3
        else:
            branches.set_fork_point(self.ctx, bid, data.draw(st.sampled_from(["anchor", "tip"])))

    @rule(
        data=st.data(),
        outcome=st.sampled_from(list(Outcome)),
        abandon=st.booleans(),
        conclusion=st.sampled_from(["found it", "a different finding", ""]),
    )
    def close(self, data: st.DataObject, outcome: Outcome, abandon: bool, conclusion: str) -> None:
        before = self.snap()
        candidates = sorted(
            b.id for b in before.branches.values() if b.kind is not BranchKind.TRUNK and b.status is not Status.CLOSED
        )
        if not candidates:
            return
        deep = [x for x in candidates if len(rules.merge_targets(before, x)) >= 2]
        bid = data.draw(st.sampled_from(deep if deep and data.draw(st.booleans()) else candidates))
        b = before.branches[bid]
        targets = rules.merge_targets(before, bid)
        target = data.draw(st.sampled_from([None, *targets])) if outcome is Outcome.MERGED else None
        effective = target or b.parent_branch_id
        if outcome is Outcome.MERGED and effective in targets and before.chain(effective):
            # What a user does before merging into a branch that is waiting for its reply: get the reply first.
            if before.messages[before.chain(effective)[-1]].role is Role.USER and data.draw(st.integers(0, 3)):
                events = asyncio.run(reply(self.ctx, self.fake, effective))
                assert events[-1]["type"] == "done", events[-1]
                before = self.snap()
        expect_error: type[Exception] | None = None
        if outcome is Outcome.MERGED and b.kind is BranchKind.ALTERNATIVE:
            expect_error = ValidationError
        elif outcome is not Outcome.ABANDONED and not conclusion:
            expect_error = ValidationError
        elif outcome is Outcome.MERGED and effective not in targets:
            expect_error = ValidationError  # the default target (the parent) is closed: Req 13.3-13.4
        elif outcome is Outcome.MERGED and effective is not None and before.chain(effective):
            if before.messages[before.chain(effective)[-1]].role is Role.USER:
                expect_error = Conflict
        counts_before = counts(self.ctx)
        if expect_error is not None:
            try:
                closing.close_branch(self.ctx, bid, outcome, conclusion, target, abandon)
            except expect_error:
                assert counts(self.ctx) == counts_before  # Property 11
                return
            raise AssertionError(f"expected {expect_error.__name__}")
        result = closing.close_branch(self.ctx, bid, outcome, conclusion, target, abandon)
        after = self.snap()
        assert after.branches[bid].status is Status.CLOSED
        if outcome is Outcome.MERGED:  # Property 9: exactly one Note, at the target's Tip, nothing else touched
            assert result.note is not None and effective is not None
            assert len(after.messages) == len(before.messages) + 1
            assert after.chain(effective)[-1] == result.note.id and after.chain(effective)[:-1] == before.chain(
                effective
            )
            for other in before.branches:
                if other != effective:
                    assert after.chain(other) == before.chain(other)
        else:
            assert result.note is None and len(after.messages) == len(before.messages)
        for d in result.abandoned:
            assert after.branches[d].status is Status.CLOSED

    @rule(data=st.data())
    def generate_text(self, data: st.DataObject) -> None:
        s = self.snap()
        tangents = sorted(b.id for b in s.branches.values() if b.kind is BranchKind.TANGENT)
        if not tangents:
            return
        bid = data.draw(st.sampled_from(tangents))
        if data.draw(st.booleans()):
            asyncio.run(generate_intent(self.ctx, self.fake, bid))
        else:
            asyncio.run(generate_standing(self.ctx, self.fake, bid))

    # -- invariants, checked after every step -----------------------------------------------------
    @invariant()
    def strict_tree_and_chains(self) -> None:  # Property 1
        s = self.snap()
        roots = [b.id for b in s.branches.values() if b.parent_branch_id is None]
        assert roots == [self.trunk] and s.branches[self.trunk].status is Status.OPEN
        for b in s.branches.values():
            assert len(rules.ancestors(s, b.id)) < len(s.branches)
            chain = s.chain(b.id)
            for i, mid in enumerate(chain):
                assert s.messages[mid].seq == i
                assert s.messages[mid].parent_message_id == (chain[i - 1] if i else b.fork_point_message_id)
            if b.parent_branch_id is not None:
                assert b.anchor is not None and s.messages[b.anchor.message_id].branch_id == b.parent_branch_id
                assert (
                    rules.anchor_error(
                        s.messages[b.anchor.message_id].content, b.anchor.start, b.anchor.end, b.anchor.quoted_text
                    )
                    is None
                )

    @invariant()
    def history_is_never_rewritten(self) -> None:  # Property 2
        s = self.snap()
        with self.ctx.store.read() as c:
            manifests = {r["id"]: r["manifest"] for r in c.execute("SELECT id, manifest FROM messages")}
            closings = [tuple(r) for r in c.execute("SELECT * FROM closings ORDER BY rowid")]
        for mid, m in self.seen_messages.items():
            assert s.messages[mid] == m
        for mid, mj in self.seen_manifests.items():
            assert manifests[mid] == mj
        assert closings[: len(self.seen_closings)] == self.seen_closings
        for bid, facts in self.seen_branch_facts.items():
            b = s.branches[bid]
            assert (b.parent_branch_id, b.kind, b.anchor) == facts[:3]
            if facts[3] is not None:
                assert b.framing_text == facts[3]
        self.seen_messages.update(s.messages)
        self.seen_manifests.update({k: v for k, v in manifests.items() if v is not None})
        self.seen_closings = closings
        for b in s.branches.values():
            old = self.seen_branch_facts.get(b.id)
            self.seen_branch_facts[b.id] = (
                b.parent_branch_id,
                b.kind,
                b.anchor,
                b.framing_text or (old[3] if old else None),
            )

    @invariant()
    def contexts_only_grow(self) -> None:  # Property 6
        s = self.snap()
        for b in s.branches.values():
            now = context.context_entries(s, b.id)
            if b.id in self.seen_contexts and s.chain(b.id):
                prev = self.seen_contexts[b.id]
                assert now[: len(prev)] == prev
            if s.chain(b.id):
                self.seen_contexts[b.id] = now
                pre = context.inherited_prefix(s, b.id)
                assert self.seen_prefix.setdefault(b.id, pre) == pre  # Req 7.6
            else:
                self.seen_contexts.pop(b.id, None)
                self.seen_prefix.pop(b.id, None)

    @invariant()
    def manifests_reproduce_what_was_sent(self) -> None:  # Req 7.7 / Property 7
        s = self.snap()
        for m in s.messages.values():
            if m.role is not Role.ASSISTANT:
                continue
            chain = s.chain(m.branch_id)
            cut = set(chain[chain.index(m.id) :])
            earlier = TreeSnapshot.build(list(s.branches.values()), [x for x in s.messages.values() if x.id not in cut])
            with self.ctx.store.read() as c:
                man = repo.get_manifest(c, m.id)
            assert man is not None and man.entries == context.context_entries(earlier, m.branch_id)

    @invariant()
    def every_reply_request_is_valid_and_free_of_generated_text(self) -> None:  # Property 12, Req 2.9
        s = self.snap()
        for bid in self.repliable():
            manifest = context.assemble(s, bid, SETTINGS)
            request = render.render(manifest, s.messages)
            check_request_shape(request)
            in_notes = sum(
                s.messages[e.id].content.count("Fake summary")
                for e in manifest.entries
                if isinstance(e, MessageEntry) and s.messages[e.id].role is Role.NOTE
            )
            framing = sum(e.text.count("Fake summary") for e in manifest.entries if isinstance(e, FramingEntry))
            assert str(request).count("Fake summary") == in_notes and framing == 0

    @invariant()
    def status_machine_and_closed_branches(self) -> None:  # Property 8
        s = self.snap()
        with self.ctx.store.read() as c:
            events = [
                tuple(r) for r in c.execute("SELECT branch_id, from_status, to_status FROM status_events ORDER BY id")
            ]
        last: dict[str, str] = {}
        for bid, frm, to in events:
            assert (frm, to) in ALLOWED and frm == last.get(bid)
            last[bid] = to
        for b in s.branches.values():
            assert last[b.id] == b.status.value
            if b.status is Status.CLOSED:
                n = len(s.chain(b.id))
                assert self.closed_len.setdefault(b.id, n) == n  # a closed Branch gains no Message (Req 12.8)
                with self.ctx.store.read() as c:
                    assert repo.closings_for(c, b.id)
            else:
                self.closed_len.pop(b.id, None)


TreeMachine.TestCase.settings = settings(
    max_examples=int(os.environ.get("TREECHAT_STATEFUL_EXAMPLES", "25")),
    stateful_step_count=25,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.data_too_large, HealthCheck.filter_too_much],
)
TestTreeMachine = TreeMachine.TestCase
