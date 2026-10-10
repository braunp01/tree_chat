"""Read-only records the domain computes over (design.md, Data Models). No I/O, no clock, no id generation."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum

type TreeId = str
type BranchId = str
type MessageId = str


class Status(StrEnum):
    PARKED = "parked"
    OPEN = "open"
    CLOSED = "closed"


class BranchKind(StrEnum):
    TRUNK = "trunk"
    TANGENT = "tangent"
    ALTERNATIVE = "alternative"


class Role(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"
    NOTE = "note"


class Outcome(StrEnum):
    MERGED = "merged"
    KEPT = "kept"
    ABANDONED = "abandoned"


class Action(StrEnum):
    PARK = "park"
    RESUME = "resume"
    CLOSE = "close"
    REOPEN = "reopen"
    SEND = "send"


@dataclass(frozen=True, slots=True)
class Anchor:
    message_id: MessageId
    start: int  # code points, inclusive
    end: int  # code points, exclusive
    quoted_text: str


@dataclass(frozen=True, slots=True)
class Message:
    id: MessageId
    branch_id: BranchId
    parent_message_id: MessageId | None
    seq: int
    role: Role
    content: str
    # Assistant only: the provider's content blocks exactly as returned, as canonical JSON text.
    blocks_json: str | None = None
    model: str | None = None
    stop_reason: str | None = None
    source_branch_id: BranchId | None = None  # Notes only
    created_at: str = ""


@dataclass(frozen=True, slots=True)
class Branch:
    id: BranchId
    tree_id: TreeId
    parent_branch_id: BranchId | None
    kind: BranchKind
    anchor: Anchor | None
    fork_point_message_id: MessageId | None
    intent: str | None
    status: Status
    framing_text: str | None  # fixed when the Branch receives its first Message (Req 7.3)
    created_at: str = ""
    status_since: str = ""


@dataclass(frozen=True, slots=True)
class TreeSnapshot:
    """Everything the domain needs about one Tree. `chains` lists each Branch's Messages in order."""

    branches: Mapping[BranchId, Branch]
    messages: Mapping[MessageId, Message]
    chains: Mapping[BranchId, tuple[MessageId, ...]] = field(default_factory=lambda: {})

    @staticmethod
    def build(branches: list[Branch], messages: list[Message]) -> TreeSnapshot:
        chains: dict[BranchId, list[Message]] = {b.id: [] for b in branches}
        for m in messages:
            chains[m.branch_id].append(m)
        return TreeSnapshot(
            branches={b.id: b for b in branches},
            messages={m.id: m for m in messages},
            chains={bid: tuple(m.id for m in sorted(ms, key=lambda m: m.seq)) for bid, ms in chains.items()},
        )

    def chain(self, branch_id: BranchId) -> tuple[MessageId, ...]:
        return self.chains.get(branch_id, ())


@dataclass(frozen=True, slots=True)
class MessageEntry:
    id: MessageId
    role: Role


@dataclass(frozen=True, slots=True)
class FramingEntry:
    branch_id: BranchId
    text: str


type Entry = MessageEntry | FramingEntry


@dataclass(frozen=True, slots=True)
class Settings:
    model: str
    effort: str
    max_tokens: int = 64000


@dataclass(frozen=True, slots=True)
class Manifest:
    """The exact record of one Context (Req 7.7)."""

    entries: tuple[Entry, ...]
    model: str
    effort: str
    max_tokens: int
    system_prompt_version: int
    # Index of the entry carrying cache breakpoint 1 (end of the Inherited_Prefix), or None.
    cache_breakpoint_after: int | None
