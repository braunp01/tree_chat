"""Builds valid TreeSnapshots in memory for domain tests, mirroring what the services will do (synthetic data)."""

from __future__ import annotations

import json
from dataclasses import replace

from treechat.domain.context import framing_text
from treechat.domain.model import (
    Anchor,
    Branch,
    BranchId,
    BranchKind,
    Message,
    MessageId,
    Role,
    Status,
    TreeSnapshot,
)
from treechat.domain.rules import tip


def fake_blocks(message_id: str, text: str) -> str:
    """Assistant content as a provider would return it: a signed thinking block, then text."""
    return json.dumps(
        [{"type": "thinking", "thinking": "", "signature": f"sig-{message_id}"}, {"type": "text", "text": text}],
        ensure_ascii=False,
    )


class Builder:
    def __init__(self) -> None:
        self.n = 0
        self.branches: dict[BranchId, Branch] = {}
        self.messages: list[Message] = []
        self.trunk = self._new_branch(None, BranchKind.TRUNK, None, None, None, Status.OPEN)

    def _id(self, prefix: str) -> str:
        self.n += 1
        return f"{prefix}{self.n:04d}"

    def _new_branch(
        self,
        parent: BranchId | None,
        kind: BranchKind,
        anchor: Anchor | None,
        fork: MessageId | None,
        intent: str | None,
        status: Status,
    ) -> BranchId:
        bid = self._id("b")
        ts = f"t{self.n:04d}"
        self.branches[bid] = Branch(bid, "tree", parent, kind, anchor, fork, intent, status, None, ts, ts)
        return bid

    def snapshot(self) -> TreeSnapshot:
        return TreeSnapshot.build(list(self.branches.values()), self.messages)

    def chain(self, bid: BranchId) -> tuple[MessageId, ...]:
        return self.snapshot().chain(bid)

    def msg(self, mid: MessageId) -> Message:
        return next(m for m in self.messages if m.id == mid)

    def add(self, bid: BranchId, role: Role, content: str = "text", source: BranchId | None = None) -> MessageId:
        snap = self.snapshot()
        b = self.branches[bid]
        chain = snap.chain(bid)
        mid = self._id("m")
        if not chain and b.kind is BranchKind.TANGENT and b.anchor is not None:
            # Req 7.3: the Framing_Block is fixed when the Branch receives its first Message.
            self.branches[bid] = replace(b, framing_text=framing_text(b.anchor.quoted_text, b.intent))
        self.messages.append(
            Message(
                id=mid,
                branch_id=bid,
                parent_message_id=tip(snap, bid),
                seq=len(chain),
                role=role,
                content=content,
                blocks_json=fake_blocks(mid, content) if role is Role.ASSISTANT else None,
                source_branch_id=source,
                created_at=f"t{self.n:04d}",
            )
        )
        return mid

    def spawn(
        self,
        anchor_mid: MessageId,
        start: int = 0,
        end: int | None = None,
        intent: str | None = None,
        fork_at_tip: bool = False,
        status: Status = Status.PARKED,
    ) -> BranchId:
        m = self.msg(anchor_mid)
        e = len(m.content) if end is None else end
        anchor = Anchor(anchor_mid, start, e, m.content[start:e])
        parent = m.branch_id  # Req 4.4: the owner of the Anchor's Message
        fork = tip(self.snapshot(), parent) if fork_at_tip else anchor_mid
        return self._new_branch(parent, BranchKind.TANGENT, anchor, fork, intent, status)

    def alternative(self, mid: MessageId) -> BranchId:
        """Req 3.2-3.3: whole-Message Anchor, Fork_Point = the predecessor."""
        m = self.msg(mid)
        anchor = Anchor(mid, 0, len(m.content), m.content)
        return self._new_branch(m.branch_id, BranchKind.ALTERNATIVE, anchor, m.parent_message_id, None, Status.OPEN)

    def set_status(self, bid: BranchId, status: Status) -> None:
        self.branches[bid] = replace(self.branches[bid], status=status)
