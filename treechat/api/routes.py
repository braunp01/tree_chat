"""HTTP routes. Shapes and wiring only: every rule lives in domain/ and services/ (design.md, API Contract)."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, Request, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from treechat.api.state import state_of
from treechat.jobs.registry import ReplyJob
from treechat.services import messages, trees, views

router = APIRouter(prefix="/api")


class ContentIn(BaseModel):
    content: str


class SendIn(BaseModel):
    parent_id: str
    content: str


class TitleIn(BaseModel):
    title: str


def _stream(job: ReplyJob) -> StreamingResponse:
    """Req 3.3, 3.8: events follow the job. A dropped connection only ends this subscription, never the job."""

    async def body() -> AsyncIterator[str]:
        async for event in job.stream():
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

    return StreamingResponse(body(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})


@router.get("/trees")
async def list_trees(request: Request) -> list[dict[str, Any]]:
    return views.list_trees(state_of(request).ctx)


@router.post("/trees", status_code=201)
async def create_tree(body: ContentIn, request: Request) -> dict[str, Any]:
    """Req 1.1: a Tree is created by its first Message, its Root. The client then requests the Reply."""
    made = trees.create_tree(state_of(request).ctx, body.content)
    return {"tree": views.tree_row_out(made.tree), "message": views.message_out(made.root)}


@router.patch("/trees/{tree_id}")
async def rename_tree(tree_id: str, body: TitleIn, request: Request) -> dict[str, Any]:
    return views.tree_row_out(trees.rename_tree(state_of(request).ctx, tree_id, body.title))


@router.get("/trees/{tree_id}")
async def get_tree(tree_id: str, request: Request) -> dict[str, Any]:
    return views.tree_out(state_of(request).ctx, tree_id)


@router.post("/trees/{tree_id}/messages", status_code=201)
async def send(tree_id: str, body: SendIn, request: Request) -> dict[str, Any]:
    """Req 3.1-3.2: a new child of the Current_Point. The client then requests the Reply."""
    return views.message_out(messages.send(state_of(request).ctx, tree_id, body.parent_id, body.content))


@router.get("/messages/{message_id}/path")
async def get_path(message_id: str, request: Request) -> dict[str, Any]:
    return views.path_out(state_of(request).ctx, message_id)


@router.post("/messages/{message_id}/reply")
async def reply(message_id: str, request: Request) -> StreamingResponse:
    st = state_of(request)
    # Start before streaming, so busy / conflict / not_found are ordinary HTTP errors (Req 3.7).
    return _stream(st.registry.start_reply(st.ctx, st.provider, message_id))


@router.get("/messages/{message_id}/live", response_model=None)
async def live(message_id: str, request: Request) -> Response:
    """Req 3.8: re-attach to a Reply in progress, with the text so far; 204 when there is none."""
    st = state_of(request)
    views.path_out(st.ctx, message_id)  # 404 for an unknown Message
    job = st.registry.get(message_id)
    return Response(status_code=204) if job is None else _stream(job)


@router.get("/messages/{message_id}/manifest")
async def manifest(message_id: str, request: Request) -> dict[str, Any]:
    return views.manifest_out(state_of(request).ctx, message_id)
