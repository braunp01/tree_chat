"""Read models: the JSON the Front_End draws from (design.md, Read models). One read transaction each, no writes."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from treechat.domain import context, rules
from treechat.domain.errors import NotFound
from treechat.domain.model import (
    Branch,
    BranchId,
    BranchKind,
    FramingEntry,
    Message,
    MessageId,
    Role,
    Status,
    TreeId,
    TreeSnapshot,
)
from treechat.domain.queue import QueueOrder, queue
from treechat.jobs.replies import message_out
from treechat.services.ctx import Ctx
from treechat.services.trees import snapshot_of_branch, tree_of_message
from treechat.store import repo
from treechat.store.codec import manifest_to_json


@dataclass(frozen=True, slots=True)
class _Extras:
    """Per-Tree facts that live outside the snapshot: closing records and generated text."""

    closings: dict[BranchId, list[repo.ClosingRow]]
    generated: dict[BranchId, str]
    standing: dict[BranchId, str]


def _extras(c: Any, tree_id: TreeId) -> _Extras:
    return _Extras(
        repo.closings_in_tree(c, tree_id),
        repo.latest_generated_in_tree(c, tree_id, "intent"),
        repo.latest_generated_in_tree(c, tree_id, "standing"),
    )


def _depths(snap: TreeSnapshot) -> dict[BranchId, int]:
    out: dict[BranchId, int] = {}
    for bid in snap.branches:
        chain: list[BranchId] = []
        cur: BranchId | None = bid
        while cur is not None and cur not in out:
            chain.append(cur)
            cur = snap.branches[cur].parent_branch_id
        d = out[cur] if cur is not None else -1
        for x in reversed(chain):
            d += 1
            out[x] = d
    return out


def _label(b: Branch, generated: str | None) -> str:
    """What to call a Branch in a list: the user's Intent, else the labelled-generated one, else the quote."""
    if b.kind is BranchKind.TRUNK:
        return "Trunk"
    return b.intent or generated or (b.anchor.quoted_text[:80] if b.anchor else "")


def _closing_out(r: repo.ClosingRow) -> dict[str, Any]:
    return {
        "outcome": r.outcome.value,
        "conclusion": r.conclusion,
        "merge_target": r.merge_target_branch_id,
        "note_message_id": r.note_message_id,
        "closed_at": r.closed_at,
    }


def _summary(snap: TreeSnapshot, b: Branch, depth: int, x: _Extras) -> dict[str, Any]:
    """A Branch summary (design.md, spawn response). `intent` is the user's; `generated_intent` is shown only
    when there is none (Req 11.4), and the client must label it as generated."""
    parent = snap.branches.get(b.parent_branch_id) if b.parent_branch_id else None
    return {
        "id": b.id,
        "tree_id": b.tree_id,
        "parent_branch_id": b.parent_branch_id,
        "parent_label": _label(parent, x.generated.get(parent.id)) if parent else None,
        "kind": b.kind.value,
        "anchor": None
        if b.anchor is None
        else {
            "message_id": b.anchor.message_id,
            "start": b.anchor.start,
            "end": b.anchor.end,
            "quoted_text": b.anchor.quoted_text,
        },
        "fork_point_message_id": b.fork_point_message_id,
        "intent": b.intent,
        "generated_intent": None if b.intent else x.generated.get(b.id),
        "standing": x.standing.get(b.id),
        "status": b.status.value,
        "depth": depth,
        "message_count": len(snap.chain(b.id)),
        "created_at": b.created_at,
        "parked_at": b.status_since if b.status is Status.PARKED else None,
        "status_since": b.status_since,
        "parent_messages_since_fork": rules.parent_messages_since_fork(snap, b.id),
        "closings": [_closing_out(r) for r in x.closings.get(b.id, [])],
    }


# --- Trees ----------------------------------------------------------------------------------------


def list_trees(ctx: Ctx) -> list[dict[str, Any]]:
    """Req 1.2."""
    with ctx.store.read() as c:
        return [
            {
                "id": t.id,
                "title": t.title,
                "trunk_branch_id": t.trunk_branch_id,
                "created_at": t.created_at,
                "last_activity_at": t.last_activity_at,
                "open_count": n_open,
                "parked_count": n_parked,
            }
            for t, n_open, n_parked in repo.list_trees(c)
        ]


def tree_out(ctx: Ctx, tree_id: TreeId) -> dict[str, Any]:
    """Req 1.1, 14.1: the Tree and a summary of every Branch (the Outline's data)."""
    with ctx.store.read() as c:
        t = repo.get_tree(c, tree_id)
        if t is None:
            raise NotFound(f"Unknown tree {tree_id}.")
        snap, x = repo.load_snapshot(c, tree_id), _extras(c, tree_id)
    depths = _depths(snap)
    return {
        "id": t.id,
        "title": t.title,
        "trunk_branch_id": t.trunk_branch_id,
        "created_at": t.created_at,
        "last_activity_at": t.last_activity_at,
        "branches": [_summary(snap, b, depths[b.id], x) for b in snap.branches.values()],
    }


def branch_out(ctx: Ctx, branch_id: BranchId) -> dict[str, Any]:
    with ctx.store.read() as c:
        snap = snapshot_of_branch(c, branch_id)
        x = _extras(c, snap.branches[branch_id].tree_id)
    return _summary(snap, snap.branches[branch_id], rules.depth(snap, branch_id), x)


def queue_out(ctx: Ctx, tree_id: TreeId, order: QueueOrder) -> list[dict[str, Any]]:
    """Req 10.2, 10.4, 10.5: Branch summaries (intent, anchor quote, parent, parked time, staleness facts)."""
    with ctx.store.read() as c:
        if repo.get_tree(c, tree_id) is None:
            raise NotFound(f"Unknown tree {tree_id}.")
        snap, x = repo.load_snapshot(c, tree_id), _extras(c, tree_id)
    depths = _depths(snap)
    return [_summary(snap, snap.branches[e.branch_id], depths[e.branch_id], x) for e in queue(snap, order)]


def map_out(ctx: Ctx, tree_id: TreeId) -> dict[str, Any]:
    """Req 14.8-14.18: structure only, no message text. Positions come from one pass over the Tree."""
    with ctx.store.read() as c:
        t = repo.get_tree(c, tree_id)
        if t is None:
            raise NotFound(f"Unknown tree {tree_id}.")
        snap, x = repo.load_snapshot(c, tree_id), _extras(c, tree_id)
    pos = rules.message_positions(snap)
    depths = _depths(snap)
    branches: list[dict[str, Any]] = []
    for b in snap.branches.values():
        chain = snap.chain(b.id)
        if chain:
            start = pos[chain[0]]
        else:
            start = pos[b.fork_point_message_id] + 1 if b.fork_point_message_id else 0
        branches.append(
            {
                "id": b.id,
                "parent_branch_id": b.parent_branch_id,
                "kind": b.kind.value,
                "status": b.status.value,
                "depth": depths[b.id],
                "intent": b.intent,
                "generated_intent": None if b.intent else x.generated.get(b.id),
                "created_at": b.created_at,
                "anchor_message_id": b.anchor.message_id if b.anchor else None,
                "anchor_position": pos[b.anchor.message_id] if b.anchor else None,
                "start_position": start,
                "message_count": len(chain),
                "messages": [{"id": m, "role": snap.messages[m].role.value, "position": pos[m]} for m in chain],
            }
        )
    return {"tree_id": t.id, "trunk_branch_id": t.trunk_branch_id, "branches": branches}


# --- Path_View ------------------------------------------------------------------------------------


def _markers(
    snap: TreeSnapshot, x: _Extras
) -> tuple[dict[MessageId, list[dict[str, Any]]], dict[MessageId, list[Any]]]:
    """Tangents (Anchor_Markers, Req 5) and Alternatives (Req 3.4) grouped by the Message they are anchored on."""
    markers: dict[MessageId, list[dict[str, Any]]] = {}
    alternatives: dict[MessageId, list[Any]] = {}
    for b in snap.branches.values():
        if b.anchor is None:
            continue
        if b.kind is BranchKind.ALTERNATIVE:
            alternatives.setdefault(b.anchor.message_id, []).append(
                {"branch_id": b.id, "status": b.status.value, "created_at": b.created_at}
            )
        else:
            markers.setdefault(b.anchor.message_id, []).append(
                {
                    "branch_id": b.id,
                    "start": b.anchor.start,
                    "end": b.anchor.end,
                    "status": b.status.value,
                    "intent": b.intent,
                    "generated_intent": None if b.intent else x.generated.get(b.id),
                    "created_at": b.created_at,
                }
            )
    for lst in markers.values():
        lst.sort(key=lambda m: (m["start"], m["end"], m["created_at"], m["branch_id"]))
    for lst in alternatives.values():
        lst.sort(key=lambda a: (a["created_at"], a["branch_id"]))
    return markers, alternatives


def view_out(ctx: Ctx, branch_id: BranchId) -> dict[str, Any]:
    """Req 5, 3.4, 13.7, 14.4: what the Path_View draws for one Branch.

    `inherited.entries` lists the Inherited_Prefix (messages and framing cards) in order; the client collapses it to
    one line using `inherited.message_count`, and `anchor_message_id` is always shown. Reading never changes Status
    (Req 10.3, 10.8).
    """
    with ctx.store.read() as c:
        snap = snapshot_of_branch(c, branch_id)
        x = _extras(c, snap.branches[branch_id].tree_id)
    b = rules.branch(snap, branch_id)
    markers, alternatives = _markers(snap, x)
    depths = _depths(snap)

    def msg(m: Message) -> dict[str, Any]:
        out = message_out(m)
        out["markers"] = markers.get(m.id, [])
        out["alternatives"] = alternatives.get(m.id, [])
        # Req 4.10: Notes in the owning Branch after this Message, which a Tangent forked here will not see.
        owner_chain = snap.chain(m.branch_id)
        out["notes_after"] = sum(
            1 for k in owner_chain[owner_chain.index(m.id) + 1 :] if snap.messages[k].role is Role.NOTE
        )
        if m.role is Role.NOTE and m.source_branch_id:
            src = snap.branches[m.source_branch_id]
            out["source"] = {"branch_id": src.id, "label": _label(src, x.generated.get(src.id))}
        return out

    entries: list[dict[str, Any]] = []
    for e in context.inherited_prefix(snap, branch_id):
        if isinstance(e, FramingEntry):
            fb = snap.branches[e.branch_id]
            entries.append({"kind": "framing", "branch_id": e.branch_id, "text": e.text, "label": _label(fb, None)})
        else:
            entries.append({"kind": "message", "message": msg(snap.messages[e.id])})
    framing = context.effective_framing(snap, b)
    chain = snap.chain(branch_id)
    tip_id = rules.tip(snap, branch_id)
    ancestors = rules.ancestors(snap, branch_id)
    return {
        "branch": _summary(snap, b, depths[branch_id], x),
        "breadcrumb": [
            {"id": a, "label": _label(snap.branches[a], x.generated.get(a)), "kind": snap.branches[a].kind.value}
            for a in reversed(ancestors)
        ],
        "inherited": {
            "message_count": sum(1 for e in entries if e["kind"] == "message"),
            "entries": entries,
            "anchor_message_id": b.anchor.message_id if b.anchor else None,
            "anchor_message": msg(snap.messages[b.anchor.message_id]) if b.anchor else None,
        },
        "framing": None
        if b.anchor is None
        else {
            "anchor_quote": b.anchor.quoted_text,
            "intent": b.intent,
            "generated_intent": None if b.intent else x.generated.get(b.id),
            "fork_point_message_id": b.fork_point_message_id,
            "text": framing.text if framing else None,
            "frozen": b.framing_text is not None,
        },
        "messages": [msg(snap.messages[m]) for m in chain],
        "tip_message_id": tip_id,
        "awaiting_reply": tip_id is not None and snap.messages[tip_id].role is Role.USER,
        "reply_in_progress": ctx.is_busy(branch_id),
        "assistant_reply_count": sum(1 for m in chain if snap.messages[m].role is Role.ASSISTANT),
        "merge_targets": [
            {"id": a, "label": _label(snap.branches[a], x.generated.get(a))}
            for a in rules.merge_targets(snap, branch_id)
        ],
        "open_descendants": [
            {"id": d, "label": _label(snap.branches[d], x.generated.get(d)), "status": snap.branches[d].status.value}
            for d in rules.descendants(snap, branch_id)
            if snap.branches[d].status is not Status.CLOSED
        ],
    }


# --- Messages -------------------------------------------------------------------------------------


def manifest_out(ctx: Ctx, message_id: MessageId) -> dict[str, Any]:
    """Req 7.8: the Context_Manifest of an assistant Message, exactly as stored."""
    with ctx.store.read() as c:
        tree_of_message(c, message_id)
        m = repo.get_manifest(c, message_id)
    if m is None:
        raise NotFound(f"Message {message_id} has no manifest; only replies do.")
    return json.loads(manifest_to_json(m))


def preview_out(ctx: Ctx, message_id: MessageId) -> dict[str, Any]:
    """Req 14.14: the first 200 characters."""
    with ctx.store.read() as c:
        text = repo.message_preview(c, message_id)
    if text is None:
        raise NotFound(f"Unknown message {message_id}.")
    return {"id": message_id, "preview": text}


def message_by_id(ctx: Ctx, message_id: MessageId) -> Message:
    with ctx.store.read() as c:
        snap = repo.load_snapshot(c, tree_of_message(c, message_id))
    return snap.messages[message_id]
