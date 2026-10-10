"""Validation, the Status machine and tree navigation. Pure functions over TreeSnapshot."""

from __future__ import annotations

from treechat.domain.errors import Conflict, NotFound, ValidationError
from treechat.domain.model import (
    Action,
    Branch,
    BranchId,
    BranchKind,
    MessageId,
    Outcome,
    Status,
    TreeSnapshot,
)

TITLE_MAX = 200
CONTENT_MAX = 100_000
INTENT_MAX = 200
CONCLUSION_MAX = 2_000


# --- Field validation (design.md, Validation rules summary) ---------------------------------------


def clean_title(title: str) -> str:
    """Req 1.4."""
    t = title.strip()
    if not t or len(t) > TITLE_MAX:
        raise ValidationError("title", f"Title must be 1 to {TITLE_MAX} characters.")
    return t


def clean_content(content: str) -> str:
    """Req 2.7. The content is stored as sent; only emptiness and length are checked after trimming."""
    t = content.strip()
    if not t or len(t) > CONTENT_MAX:
        raise ValidationError("content", f"Message must be 1 to {CONTENT_MAX:,} characters.")
    return content


def clean_intent(intent: str | None) -> str | None:
    """Req 4.3: optional; empty means none."""
    if intent is None:
        return None
    t = intent.strip()
    if len(t) > INTENT_MAX:
        raise ValidationError("intent", f"Intent must be at most {INTENT_MAX} characters.")
    return t or None


def clean_conclusion(outcome: Outcome, conclusion: str | None) -> str | None:
    """Req 12.2-12.3: required for merged and kept, optional for abandoned."""
    t = (conclusion or "").strip()
    if len(t) > CONCLUSION_MAX:
        raise ValidationError("conclusion", f"Conclusion must be at most {CONCLUSION_MAX:,} characters.")
    if not t and outcome is not Outcome.ABANDONED:
        raise ValidationError("conclusion", "A conclusion is required to close as merged or kept.")
    return t or None


def anchor_error(content: str, start: int, end: int, quoted_text: str) -> str | None:
    """Req 4.5: offsets are code points (Python str indices); the slice must equal the quote."""
    if not (0 <= start < end <= len(content)):
        return f"Offsets {start}-{end} are outside the message (length {len(content)})."
    if content[start:end] != quoted_text:
        return f"quoted_text does not match the message text at {start}-{end}."
    return None


# --- Status machine (Req 10.1, 12.7-12.9, 2.8) ---------------------------------------------------

_TRANSITIONS: dict[tuple[Status, Action], Status] = {
    (Status.OPEN, Action.PARK): Status.PARKED,
    (Status.PARKED, Action.RESUME): Status.OPEN,
    (Status.OPEN, Action.CLOSE): Status.CLOSED,
    (Status.PARKED, Action.CLOSE): Status.CLOSED,
    (Status.CLOSED, Action.REOPEN): Status.OPEN,
    (Status.OPEN, Action.SEND): Status.OPEN,
    (Status.PARKED, Action.SEND): Status.OPEN,
}


def transition(status: Status, action: Action, kind: BranchKind) -> Status:
    if kind is BranchKind.TRUNK and action is not Action.SEND:
        raise Conflict("The Trunk is always open; it cannot be parked, closed or reopened.")
    nxt = _TRANSITIONS.get((status, action))
    if nxt is None:
        raise Conflict(f"Cannot {action.value} a branch that is {status.value}.")
    return nxt


def check_outcome(kind: BranchKind, outcome: Outcome) -> None:
    """Req 12.9: an Alternative may not be merged."""
    if kind is BranchKind.ALTERNATIVE and outcome is Outcome.MERGED:
        raise ValidationError("outcome", "An alternative cannot be merged; close it as kept or abandoned.")


# --- Tree navigation ------------------------------------------------------------------------------


def branch(snap: TreeSnapshot, branch_id: BranchId) -> Branch:
    b = snap.branches.get(branch_id)
    if b is None:
        raise NotFound(f"Unknown branch {branch_id}.")
    return b


def ancestors(snap: TreeSnapshot, branch_id: BranchId) -> tuple[BranchId, ...]:
    """Nearest first, ending at the Trunk."""
    out: list[BranchId] = []
    cur = branch(snap, branch_id).parent_branch_id
    while cur is not None:
        out.append(cur)
        cur = branch(snap, cur).parent_branch_id
    return tuple(out)


def children(snap: TreeSnapshot, branch_id: BranchId) -> tuple[BranchId, ...]:
    return tuple(
        b.id
        for b in sorted(snap.branches.values(), key=lambda b: (b.created_at, b.id))
        if b.parent_branch_id == branch_id
    )


def descendants(snap: TreeSnapshot, branch_id: BranchId) -> tuple[BranchId, ...]:
    out: list[BranchId] = []
    stack = list(reversed(children(snap, branch_id)))
    while stack:
        b = stack.pop()
        out.append(b)
        stack.extend(reversed(children(snap, b)))
    return tuple(out)


def depth(snap: TreeSnapshot, branch_id: BranchId) -> int:
    return len(ancestors(snap, branch_id))


def merge_targets(snap: TreeSnapshot, branch_id: BranchId) -> tuple[BranchId, ...]:
    """Req 13.3: ancestors that are not closed, nearest first. The Trunk is never closed."""
    return tuple(a for a in ancestors(snap, branch_id) if snap.branches[a].status is not Status.CLOSED)


def tip(snap: TreeSnapshot, branch_id: BranchId) -> MessageId | None:
    """Glossary Tip: the last Message, or the Fork_Point when the Branch has none."""
    chain = snap.chain(branch_id)
    return chain[-1] if chain else branch(snap, branch_id).fork_point_message_id


def message_path(snap: TreeSnapshot, message_id: MessageId | None) -> tuple[MessageId, ...]:
    """Messages from the Trunk's first Message to `message_id`, inclusive, following parent links."""
    out: list[MessageId] = []
    cur = message_id
    while cur is not None:
        out.append(cur)
        cur = snap.messages[cur].parent_message_id
    out.reverse()
    return tuple(out)


def conversation_position(snap: TreeSnapshot, message_id: MessageId) -> int:
    """Glossary Conversation_Position: how many Messages precede it on its path."""
    return len(message_path(snap, message_id)) - 1


def parent_messages_since_fork(snap: TreeSnapshot, branch_id: BranchId) -> int:
    """Req 10.5: how many Messages the parent gained after this Branch's Fork_Point."""
    b = branch(snap, branch_id)
    if b.parent_branch_id is None:
        return 0
    chain = snap.chain(b.parent_branch_id)
    if b.fork_point_message_id in chain:
        return len(chain) - chain.index(b.fork_point_message_id) - 1
    return len(chain)
