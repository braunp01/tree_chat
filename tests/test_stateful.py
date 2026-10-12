"""Properties 1, 2, 3 and 6 over random sequences of every operation (design.md, Testing Strategy).

Rules: create a Tree, send from a random point (valid or not), reply with a random Fake outcome, ask for a second
reply, send invalid content. Invariants are checked after every step. No model calls.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any

from hypothesis import settings
from hypothesis import strategies as st
from hypothesis.stateful import RuleBasedStateMachine, invariant, precondition, rule

from treechat.domain import rules as tree_rules
from treechat.domain.errors import Conflict, ValidationError
from treechat.domain.model import Role
from treechat.jobs.replies import run_reply
from treechat.provider.fake import FakeProvider
from treechat.services import messages, trees
from treechat.store import repo

from .helpers import make_ctx

TEXT = st.text(alphabet="abc xyz😀é", min_size=1, max_size=30).filter(lambda t: t.strip())
OUTCOMES = st.sampled_from(["ok", "ok", "ok", "fail", "refuse", "truncate", "fallback", "too_large"])


class TreeChat(RuleBasedStateMachine):
    def __init__(self) -> None:
        super().__init__()
        self.dir = Path(tempfile.mkdtemp())
        self.ctx = make_ctx(self.dir)
        self.provider = FakeProvider()
        self.seen: dict[str, tuple[Any, ...]] = {}

    def teardown(self) -> None:
        shutil.rmtree(self.dir, ignore_errors=True)

    def rows(self) -> list[Any]:
        with self.ctx.store.read() as c:
            return [tuple(r) for r in c.execute("SELECT * FROM messages ORDER BY id")]

    def tree_ids(self) -> list[str]:
        return [t.id for t in trees.list_trees(self.ctx)]

    def snap(self, tree_id: str):  # noqa: ANN201
        with self.ctx.store.read() as c:
            return repo.load_snapshot(c, tree_id)

    @rule(text=TEXT)
    def new_tree(self, text: str) -> None:
        trees.create_tree(self.ctx, text)

    @precondition(lambda self: self.tree_ids())
    @rule(data=st.data(), text=TEXT)
    def send_from_a_point(self, data: st.DataObject, text: str) -> None:
        tid = data.draw(st.sampled_from(self.tree_ids()))
        s = self.snap(tid)
        point = data.draw(st.sampled_from(sorted(s.messages)))
        before = self.rows()
        if s.messages[point].role is Role.ASSISTANT:
            m = messages.send(self.ctx, tid, point, text)
            assert m.parent_id == point
        else:
            try:
                messages.send(self.ctx, tid, point, text)
            except Conflict:
                assert self.rows() == before  # Property 6
            else:
                raise AssertionError("sent from a user message")  # Req 3.2

    @precondition(lambda self: self.tree_ids())
    @rule(data=st.data(), outcome=OUTCOMES)
    def reply(self, data: st.DataObject, outcome: str) -> None:
        pending = [
            m.id
            for tid in self.tree_ids()
            for s in [self.snap(tid)]
            for m in s.messages.values()
            if m.role is Role.USER and tree_rules.reply_of(s, m.id) is None
        ]
        if not pending:
            return
        uid = data.draw(st.sampled_from(sorted(pending)))
        before = self.rows()
        self.provider.then(outcome)
        events: list[dict[str, Any]] = []
        asyncio.run(run_reply(self.ctx, self.provider, messages.prepare_reply(self.ctx, uid), events.append))
        if outcome in ("fail", "refuse", "too_large"):
            assert events[-1]["type"] == "error" and self.rows() == before  # Req 3.5, Property 6
        else:
            assert events[-1]["type"] == "done" and events[-1]["message"]["parent_id"] == uid

    @precondition(lambda self: self.tree_ids())
    @rule(data=st.data())
    def ask_for_a_second_reply(self, data: st.DataObject) -> None:
        answered = [
            m.parent_id
            for tid in self.tree_ids()
            for m in self.snap(tid).messages.values()
            if m.role is Role.ASSISTANT and m.parent_id is not None
        ]
        if answered:
            try:
                messages.prepare_reply(self.ctx, data.draw(st.sampled_from(sorted(answered))))
            except Conflict:
                return
            raise AssertionError("a second reply was allowed")  # Req 5.2

    @precondition(lambda self: self.tree_ids())
    @rule(data=st.data(), text=st.sampled_from(["", "   ", "x" * 100_001]))
    def send_invalid_content(self, data: st.DataObject, text: str) -> None:
        tid = data.draw(st.sampled_from(self.tree_ids()))
        replies = [m.id for m in self.snap(tid).messages.values() if m.role is Role.ASSISTANT]
        before = self.rows()
        try:
            messages.send(self.ctx, tid, replies[0] if replies else "none", text)
        except ValidationError as e:
            assert e.fields == ("content",)
        assert self.rows() == before

    @invariant()
    def history_is_never_rewritten(self) -> None:  # Property 1, Req 5.1
        now = {r[0]: r for r in self.rows()}
        for mid, row in self.seen.items():
            assert now[mid] == row
        self.seen = now

    @invariant()
    def every_tree_has_the_right_shape(self) -> None:  # Property 2, Req 5.3
        for tid in self.tree_ids():
            s = self.snap(tid)
            roots = [m for m in s.messages.values() if m.parent_id is None]
            assert len(roots) == 1 and roots[0].role is Role.USER
            for m in s.messages.values():
                if m.parent_id is not None:
                    assert s.messages[m.parent_id].role is not m.role
                if m.role is Role.USER:
                    assert sum(1 for k in s.kids(m.id) if s.messages[k].role is Role.ASSISTANT) <= 1

    @invariant()
    def every_reply_saw_exactly_its_path(self) -> None:  # Property 3, Req 4.1
        with self.ctx.store.read() as c:
            for tid in self.tree_ids():
                s = repo.load_snapshot(c, tid)
                for m in s.messages.values():
                    if m.role is Role.ASSISTANT:
                        manifest = repo.get_manifest(c, m.id)
                        assert manifest is not None and m.parent_id is not None
                        assert [e.id for e in manifest.entries] == list(tree_rules.path(s, m.parent_id))


TreeChat.TestCase.settings = settings(
    max_examples=int(os.environ.get("TREECHAT_STATEFUL_EXAMPLES", "200")), stateful_step_count=40, deadline=None
)
test_tree_chat = TreeChat.TestCase
