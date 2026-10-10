"""Context assembly: what the model sees for each reply (Req 7). Pure and deterministic."""

from __future__ import annotations

from treechat.domain.model import (
    Branch,
    BranchId,
    BranchKind,
    Entry,
    FramingEntry,
    Manifest,
    MessageEntry,
    MessageId,
    Settings,
    TreeSnapshot,
)
from treechat.domain.rules import branch, tip

SYSTEM_PROMPT_VERSION = 1


def framing_text(anchor_quote: str, intent: str | None) -> str:
    """Req 7.3: the Anchor quote, the user's Intent if written, and the stay-on-tangent instruction.
    A Generated_Intent is never passed here (Req 11.5)."""
    intent_line = (
        f"The user's intent for this tangent: {intent}"
        if intent
        else "The user did not state an intent for this tangent."
    )
    return (
        "<tree_chat_framing>\n"
        "The conversation has branched into a tangent about this passage from earlier in it:\n"
        f"<anchor>{anchor_quote}</anchor>\n"
        f"{intent_line}\n"
        "Stay on this tangent. Answer about the passage and the intent; do not continue the earlier "
        "thread unless the user asks.\n"
        "</tree_chat_framing>"
    )


def _attr(text: str) -> str:
    return text.replace("&", "&amp;").replace('"', "&quot;").replace("<", "&lt;").replace("\n", " ")


def note_text(label: str, anchor_quote: str, conclusion: str) -> str:
    """Req 13.2: the Note body exactly as stored and as sent to the model (design.md, Note format)."""
    return (
        f'<tree_chat_note from_branch="{_attr(label)}" anchored_on="{_attr(anchor_quote[:200])}">\n'
        f"{conclusion}\n"
        "</tree_chat_note>"
    )


def note_label(intent: str | None, generated_intent: str | None, anchor_quote: str) -> str:
    """Req 13.2: Intent, else Generated_Intent, else the first 80 characters of the Anchor quote."""
    return intent or generated_intent or anchor_quote[:80]


def effective_framing(snap: TreeSnapshot, b: Branch) -> FramingEntry | None:
    """The Framing_Block that applies to a Branch's own Messages (Req 7.1, 3.5).

    A Tangent has its own. An Alternative that replaces its parent's *first* Message (same Fork_Point as the
    parent) stands where that Message stood, so it keeps the parent's framing; any other Alternative inherits
    the framing through its prefix. The Trunk has none.
    """
    cur = b
    while cur.kind is BranchKind.ALTERNATIVE and cur.parent_branch_id is not None:
        parent = branch(snap, cur.parent_branch_id)
        if cur.fork_point_message_id != parent.fork_point_message_id:
            return None
        cur = parent
    if cur.kind is BranchKind.TANGENT and cur.framing_text is not None:
        return FramingEntry(cur.id, cur.framing_text)
    return None


def _own_entries(snap: TreeSnapshot, b: Branch, ids: tuple[MessageId, ...]) -> list[Entry]:
    """A Branch's own Messages, with its Framing_Block once, immediately after its first user Message (Req 7.1)."""
    framing = effective_framing(snap, b)
    out: list[Entry] = []
    for i, mid in enumerate(ids):
        out.append(MessageEntry(mid, snap.messages[mid].role))
        if i == 0 and framing is not None:
            out.append(framing)
    return out


def _own_through(snap: TreeSnapshot, branch_id: BranchId, through: MessageId | None) -> list[Entry]:
    b = branch(snap, branch_id)
    chain = snap.chain(branch_id)
    if through is None or through not in chain:
        if through is not None and through != b.fork_point_message_id:
            raise ValueError(f"{through} is not known to branch {branch_id}")
        return []
    return _own_entries(snap, b, chain[: chain.index(through) + 1])


def knowledge(snap: TreeSnapshot, branch_id: BranchId, through: MessageId | None) -> tuple[Entry, ...]:
    """What `branch_id` knew at `through` (one of its own Messages, or its Fork_Point): its Inherited_Prefix,
    then its own entries up to `through`. Iterative, so tree depth is unbounded (Req 4.7)."""
    levels: list[tuple[BranchId, MessageId | None]] = []
    cur_b, cur_t = branch_id, through
    while True:
        levels.append((cur_b, cur_t))
        b = branch(snap, cur_b)
        if b.parent_branch_id is None:
            break
        cur_b, cur_t = b.parent_branch_id, b.fork_point_message_id
    out: list[Entry] = []
    for bid, t in reversed(levels):
        out.extend(_own_through(snap, bid, t))
    return tuple(out)


def inherited_prefix(snap: TreeSnapshot, branch_id: BranchId) -> tuple[Entry, ...]:
    """Glossary Inherited_Prefix: the parent's Context through the Fork_Point, including ancestors' framing."""
    b = branch(snap, branch_id)
    if b.parent_branch_id is None:
        return ()
    return knowledge(snap, b.parent_branch_id, b.fork_point_message_id)


def context_entries(snap: TreeSnapshot, branch_id: BranchId) -> tuple[Entry, ...]:
    """The Context for the next reply in `branch_id` (Req 7.1)."""
    return knowledge(snap, branch_id, tip(snap, branch_id))


def assemble(snap: TreeSnapshot, branch_id: BranchId, settings: Settings) -> Manifest:
    entries = context_entries(snap, branch_id)
    prefix_len = len(inherited_prefix(snap, branch_id))
    return Manifest(
        entries=entries,
        model=settings.model,
        effort=settings.effort,
        max_tokens=settings.max_tokens,
        system_prompt_version=SYSTEM_PROMPT_VERSION,
        cache_breakpoint_after=prefix_len - 1 if prefix_len > 0 else None,
    )
