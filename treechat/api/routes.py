"""HTTP routes. Shapes and wiring only: every rule lives in domain/ and services/ (design.md, API Contract)."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, Request, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from treechat.api.state import state_of
from treechat.domain.errors import Conflict, ValidationError
from treechat.domain.model import Action, Outcome, Role, Status
from treechat.domain.queue import QueueOrder
from treechat.jobs.registry import ReplyJob
from treechat.jobs.replies import draft_conclusion, generate_intent, generate_standing, message_out
from treechat.provider.base import ErrorCategory, ProviderError
from treechat.services import branches, closing, messages, trees, views

router = APIRouter(prefix="/api")


# --- Request bodies -------------------------------------------------------------------------------


class TitleIn(BaseModel):
    title: str


class AnchorIn(BaseModel):
    message_id: str
    start: int
    end: int
    quoted_text: str


class SpawnIn(BaseModel):
    parent_branch_id: str | None = None  # accepted and ignored: the parent comes from the Anchor (Req 4.4)
    anchor: AnchorIn
    intent: str | None = None
    fork_at: str = "anchor"
    status: str = "parked"


class PatchBranchIn(BaseModel):
    intent: str | None = None
    fork_at: str | None = None


class ContentIn(BaseModel):
    content: str


class AlternativeIn(BaseModel):
    content: str | None = None


class CloseIn(BaseModel):
    outcome: str
    conclusion: str | None = None
    merge_target: str | None = None
    abandon_descendants: bool = False


def _enum[E: (Status, Outcome, QueueOrder)](kind: type[E], value: str, field: str) -> E:
    try:
        return kind(value)
    except ValueError:
        allowed = ", ".join(e.value for e in kind)
        raise ValidationError(field, f"{field} must be one of: {allowed}.") from None


def _sse(event: dict[str, Any]) -> str:
    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"


def _stream(job: ReplyJob) -> StreamingResponse:
    """Req 2.2, 2.6: events follow the job. A dropped connection only ends this subscription, never the job."""

    async def body() -> AsyncIterator[str]:
        async for event in job.stream():
            yield _sse(event)

    return StreamingResponse(body(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})


# --- Trees ----------------------------------------------------------------------------------------


@router.get("/trees")
async def list_trees(request: Request) -> list[dict[str, Any]]:
    return views.list_trees(state_of(request).ctx)


@router.post("/trees", status_code=201)
async def create_tree(request: Request) -> dict[str, Any]:
    ctx = state_of(request).ctx
    tree_id, _ = trees.create_tree(ctx)
    return views.tree_out(ctx, tree_id)


@router.patch("/trees/{tree_id}")
async def rename_tree(tree_id: str, body: TitleIn, request: Request) -> dict[str, Any]:
    ctx = state_of(request).ctx
    trees.rename_tree(ctx, tree_id, body.title)
    return views.tree_out(ctx, tree_id)


@router.get("/trees/{tree_id}")
async def get_tree(tree_id: str, request: Request) -> dict[str, Any]:
    return views.tree_out(state_of(request).ctx, tree_id)


@router.get("/trees/{tree_id}/map")
async def get_map(tree_id: str, request: Request) -> dict[str, Any]:
    return views.map_out(state_of(request).ctx, tree_id)


@router.get("/trees/{tree_id}/queue")
async def get_queue(tree_id: str, request: Request, order: str = "oldest") -> list[dict[str, Any]]:
    return views.queue_out(state_of(request).ctx, tree_id, _enum(QueueOrder, order, "order"))


# --- Branches -------------------------------------------------------------------------------------


@router.get("/branches/{branch_id}/view")
async def get_view(branch_id: str, request: Request) -> dict[str, Any]:
    return views.view_out(state_of(request).ctx, branch_id)


@router.post("/branches", status_code=201)
async def spawn(body: SpawnIn, request: Request) -> dict[str, Any]:
    st = state_of(request)
    a = body.anchor
    b = branches.spawn_tangent(
        st.ctx,
        a.message_id,
        a.start,
        a.end,
        a.quoted_text,
        body.intent,
        body.fork_at,
        _enum(Status, body.status, "status"),
    )
    if b.intent is None:  # Req 4.9, 11.1: in the background; spawning does not wait
        st.registry.spawn_background(generate_intent(st.ctx, st.provider, b.id))
    return views.branch_out(st.ctx, b.id)


@router.patch("/branches/{branch_id}")
async def patch_branch(branch_id: str, body: PatchBranchIn, request: Request) -> dict[str, Any]:
    ctx = state_of(request).ctx
    if "intent" in body.model_fields_set:
        branches.set_intent(ctx, branch_id, body.intent)  # Req 11.4
    if "fork_at" in body.model_fields_set:
        if body.fork_at is None:
            raise ValidationError("fork_point", "fork_at must be 'anchor' or 'tip'.")
        branches.set_fork_point(ctx, branch_id, body.fork_at)  # Req 9.2-9.3
    return views.branch_out(ctx, branch_id)


@router.post("/branches/{branch_id}/messages", status_code=201)
async def send(branch_id: str, body: ContentIn, request: Request) -> dict[str, Any]:
    return message_out(messages.send_message(state_of(request).ctx, branch_id, body.content))


@router.post("/branches/{branch_id}/reply")
async def reply(branch_id: str, request: Request) -> StreamingResponse:
    st = state_of(request)
    # Start before streaming, so busy / conflict / not_found are ordinary HTTP errors (Req 2.5, 2.9).
    return _stream(st.registry.start_reply(st.ctx, st.provider, branch_id))


@router.get("/branches/{branch_id}/live", response_model=None)
async def live(branch_id: str, request: Request) -> Response:
    """Req 2.6: re-attach to a reply in progress, with the text so far; 204 when there is none."""
    st = state_of(request)
    views.branch_out(st.ctx, branch_id)  # 404 for an unknown Branch
    job = st.registry.get(branch_id)
    return Response(status_code=204) if job is None else _stream(job)


@router.post("/branches/{branch_id}/park")
async def park(branch_id: str, request: Request) -> dict[str, Any]:
    st = state_of(request)
    branches.change_status(st.ctx, branch_id, Action.PARK)
    st.registry.spawn_background(generate_standing(st.ctx, st.provider, branch_id))  # Req 11.2
    return views.branch_out(st.ctx, branch_id)


@router.post("/branches/{branch_id}/resume")
async def resume(branch_id: str, request: Request) -> dict[str, Any]:
    st = state_of(request)
    branches.change_status(st.ctx, branch_id, Action.RESUME)
    return views.branch_out(st.ctx, branch_id)


@router.post("/branches/{branch_id}/reopen")
async def reopen(branch_id: str, request: Request) -> dict[str, Any]:
    st = state_of(request)
    branches.change_status(st.ctx, branch_id, Action.REOPEN)
    return views.branch_out(st.ctx, branch_id)


@router.post("/branches/{branch_id}/conclusion-draft")
async def conclusion_draft(branch_id: str, request: Request) -> dict[str, str]:
    """Req 12.1: not stored. Without credentials the draft is empty so the close panel still works."""
    st = state_of(request)
    try:
        return {"text": await draft_conclusion(st.ctx, st.provider, branch_id)}
    except ProviderError as exc:
        if exc.category is ErrorCategory.PROVIDER_UNAVAILABLE:
            return {"text": ""}
        raise


@router.post("/branches/{branch_id}/close")
async def close(branch_id: str, body: CloseIn, request: Request) -> dict[str, Any]:
    ctx = state_of(request).ctx
    result = closing.close_branch(
        ctx,
        branch_id,
        _enum(Outcome, body.outcome, "outcome"),
        body.conclusion,
        body.merge_target,
        body.abandon_descendants,
    )
    out = views.branch_out(ctx, branch_id)
    out["note_message_id"] = result.note.id if result.note else None
    out["abandoned_branch_ids"] = list(result.abandoned)
    return out


# --- Messages -------------------------------------------------------------------------------------


@router.post("/messages/{message_id}/alternatives", status_code=201)
async def alternatives(message_id: str, request: Request, body: AlternativeIn | None = None) -> dict[str, Any]:
    """Req 3.2-3.3: edit a user Message (`content` required) or regenerate a reply (no body). Returns the new
    Alternative; for a regeneration the client then requests its reply, as for any Branch whose Tip is a user turn
    or empty."""
    ctx = state_of(request).ctx
    role = views.message_by_id(ctx, message_id).role
    if role is Role.USER:
        if body is None or body.content is None:
            raise ValidationError("content", "Editing a message needs the new content.")
        alt = messages.edit_message(ctx, message_id, body.content)
    elif role is Role.ASSISTANT:
        alt = messages.regenerate_message(ctx, message_id)
    else:
        raise Conflict("Notes cannot be edited or regenerated.")
    return views.branch_out(ctx, alt.id)


@router.get("/messages/{message_id}/manifest")
async def manifest(message_id: str, request: Request) -> dict[str, Any]:
    return views.manifest_out(state_of(request).ctx, message_id)


@router.get("/messages/{message_id}/preview")
async def preview(message_id: str, request: Request) -> dict[str, Any]:
    return views.preview_out(state_of(request).ctx, message_id)
