"""Read-only records the domain computes over (design.md, Data Model). No I/O, no clock, no id generation."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum

type TreeId = str
type MessageId = str


class Role(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"


@dataclass(frozen=True, slots=True)
class Message:
    id: MessageId
    tree_id: TreeId
    parent_id: MessageId | None  # None only for the Tree's Root
    role: Role
    content: str
    # Assistant only: the provider's content blocks exactly as returned, as canonical JSON text.
    blocks_json: str | None = None
    model: str | None = None
    stop_reason: str | None = None
    created_at: str = ""


@dataclass(frozen=True, slots=True)
class TreeSnapshot:
    """Every Message of one Tree. `children` lists each Message's children in creation order."""

    messages: Mapping[MessageId, Message]
    root_id: MessageId | None
    children: Mapping[MessageId, tuple[MessageId, ...]] = field(default_factory=lambda: {})

    @staticmethod
    def build(messages: list[Message]) -> TreeSnapshot:
        kids: dict[MessageId, list[Message]] = {m.id: [] for m in messages}
        root: MessageId | None = None
        for m in messages:
            if m.parent_id is None:
                root = m.id
            elif m.parent_id in kids:
                kids[m.parent_id].append(m)
        return TreeSnapshot(
            messages={m.id: m for m in messages},
            root_id=root,
            children={k: tuple(c.id for c in sorted(v, key=lambda c: (c.created_at, c.id))) for k, v in kids.items()},
        )

    def kids(self, message_id: MessageId) -> tuple[MessageId, ...]:
        return self.children.get(message_id, ())


@dataclass(frozen=True, slots=True)
class MessageEntry:
    id: MessageId
    role: Role


@dataclass(frozen=True, slots=True)
class Settings:
    model: str
    effort: str
    max_tokens: int = 64000


@dataclass(frozen=True, slots=True)
class Manifest:
    """The exact record of one Context (Req 4.4): the Path to the user Message, in order."""

    entries: tuple[MessageEntry, ...]
    model: str
    effort: str
    max_tokens: int
    system_prompt_version: int
    # Index of the entry carrying the cache breakpoint (the last Message before the new user Message), or None.
    cache_breakpoint_after: int | None


@dataclass(frozen=True, slots=True)
class BranchInfo:
    """A derived Branch (glossary): a run from the Root, or from a child of a Fork, down to the next Fork or Leaf."""

    id: MessageId  # the id of its first Message
    parent_branch_id: MessageId | None
    message_ids: tuple[MessageId, ...]
