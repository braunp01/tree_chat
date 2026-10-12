"""Tree rules: validation, Paths, Replies, the default point and derived Branches (Req 1-3, 5, 6). Pure."""

from __future__ import annotations

from treechat.domain.errors import Conflict, NotFound, ValidationError
from treechat.domain.model import BranchInfo, Message, MessageId, Role, TreeSnapshot

TITLE_MAX = 200
CONTENT_MAX = 100_000
TITLE_FROM_ROOT = 60


def clean_title(title: str) -> str:
    """Req 1.4."""
    t = title.strip()
    if not t or len(t) > TITLE_MAX:
        raise ValidationError("title", f"Title must be 1 to {TITLE_MAX} characters.")
    return t


def clean_content(content: str) -> str:
    """Req 3.9. The content is stored as sent; only emptiness and length are checked after trimming."""
    t = content.strip()
    if not t or len(t) > CONTENT_MAX:
        raise ValidationError("content", f"Message must be 1 to {CONTENT_MAX:,} characters.")
    return content


def title_from_root(content: str) -> str:
    """Req 1.3: the first 60 characters of the Root, on one line."""
    return " ".join(content.split())[:TITLE_FROM_ROOT].strip()


def message(snap: TreeSnapshot, message_id: MessageId) -> None:
    if message_id not in snap.messages:
        raise NotFound(f"Unknown message {message_id}.")


def path(snap: TreeSnapshot, message_id: MessageId) -> tuple[MessageId, ...]:
    """Glossary Path: the Messages from the Root down to `message_id`, inclusive. Iterative: depth is unbounded."""
    message(snap, message_id)
    out: list[MessageId] = []
    cur: MessageId | None = message_id
    while cur is not None:
        out.append(cur)
        cur = snap.messages[cur].parent_id
    out.reverse()
    return tuple(out)


def check_parent(snap: TreeSnapshot, parent_id: MessageId) -> None:
    """Req 3.2, 5.3: a new user Message hangs from an assistant Message of the same Tree."""
    p = snap.messages.get(parent_id)
    if p is None:
        raise Conflict("You can only continue from a reply in this tree.")
    if p.role is not Role.ASSISTANT:
        raise Conflict("You can only continue from a reply; this message is still waiting for its reply.")


def reply_of(snap: TreeSnapshot, user_message_id: MessageId) -> MessageId | None:
    """Glossary Reply: a user Message has at most one (Req 5.3)."""
    for c in snap.kids(user_message_id):
        if snap.messages[c].role is Role.ASSISTANT:
            return c
    return None


def check_can_reply(snap: TreeSnapshot, user_message_id: MessageId) -> None:
    """Req 3.3: only a user Message without a Reply can get one."""
    message(snap, user_message_id)
    if snap.messages[user_message_id].role is not Role.USER:
        raise Conflict("Only your own messages get a reply.")
    if reply_of(snap, user_message_id) is not None:
        raise Conflict("This message already has its reply.")


def default_point(snap: TreeSnapshot) -> MessageId | None:
    """Req 2.2: the most recently created Reply, or the Root while its Reply is pending."""
    replies = [m for m in snap.messages.values() if m.role is Role.ASSISTANT]
    if replies:
        return max(replies, key=lambda m: (m.created_at, m.id)).id
    return snap.root_id


def latest_reply_below(snap: TreeSnapshot, message_id: MessageId) -> MessageId | None:
    """Req 2.4: the most recently created Reply among the descendants of `message_id`, if it has any."""
    best: Message | None = None
    stack = list(snap.kids(message_id))
    while stack:
        m = snap.messages[stack.pop()]
        if m.role is Role.ASSISTANT and (best is None or (m.created_at, m.id) > (best.created_at, best.id)):
            best = m
        stack.extend(snap.kids(m.id))
    return best.id if best else None


def branches(snap: TreeSnapshot) -> tuple[BranchInfo, ...]:
    """Req 6: derived Branches in pre-order (siblings by creation time). A Branch starts at the Root or at a child of
    a Fork (a Message with more than one child) and runs down through single children. One pass over the Messages."""
    if snap.root_id is None:
        return ()
    out: list[BranchInfo] = []
    stack: list[tuple[MessageId, MessageId | None]] = [(snap.root_id, None)]
    while stack:
        start, parent_branch = stack.pop()
        run = [start]
        kids = snap.kids(start)
        while len(kids) == 1:
            run.append(kids[0])
            kids = snap.kids(kids[0])
        out.append(BranchInfo(start, parent_branch, tuple(run)))
        for k in reversed(kids):
            stack.append((k, start))
    return tuple(out)
