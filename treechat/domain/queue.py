"""The Queue of parked Branches: ordering and staleness facts (Req 10.2, 10.4-10.5)."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from treechat.domain.model import Branch, BranchId, Status, TreeSnapshot
from treechat.domain.rules import parent_messages_since_fork


class QueueOrder(StrEnum):
    OLDEST = "oldest"
    NEWEST = "newest"
    PARENT = "parent"


@dataclass(frozen=True, slots=True)
class QueueEntry:
    branch_id: BranchId
    parked_at: str
    parent_messages_since_fork: int  # facts only; nothing is closed or hidden automatically (Req 10.5)


def queue(snap: TreeSnapshot, order: QueueOrder = QueueOrder.OLDEST) -> tuple[QueueEntry, ...]:
    parked: list[Branch] = [b for b in snap.branches.values() if b.status is Status.PARKED]
    match order:
        case QueueOrder.OLDEST:
            parked.sort(key=lambda b: (b.status_since, b.id))
        case QueueOrder.NEWEST:
            parked.sort(key=lambda b: (b.status_since, b.id), reverse=True)
        case QueueOrder.PARENT:
            parked.sort(key=lambda b: (b.parent_branch_id or "", b.status_since, b.id))
    return tuple(QueueEntry(b.id, b.status_since, parent_messages_since_fork(snap, b.id)) for b in parked)
