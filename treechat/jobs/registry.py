"""One reply job per Branch, independent of any browser connection (Req 2.5, 2.6)."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Coroutine
from typing import Any

from treechat.domain.errors import Busy
from treechat.domain.model import BranchId
from treechat.jobs.replies import run_reply
from treechat.provider.base import Provider
from treechat.services.ctx import Ctx
from treechat.services.messages import PreparedReply, prepare_reply

log = logging.getLogger("treechat.jobs")

TERMINAL = ("done", "error")


class ReplyJob:
    def __init__(self, job_id: str, branch_id: BranchId) -> None:
        self.job_id = job_id
        self.branch_id = branch_id
        self.finished = False
        self._events: list[dict[str, Any]] = []
        self._queues: list[asyncio.Queue[dict[str, Any]]] = []

    def emit(self, event: dict[str, Any]) -> None:
        self._events.append(event)
        if event["type"] in TERMINAL:
            self.finished = True
        for q in self._queues:
            q.put_nowait(event)

    def _replay(self) -> list[dict[str, Any]]:
        """Everything so far, with the streamed text joined so a late subscriber gets one catch-up chunk."""
        out: list[dict[str, Any]] = [{"type": "started", "job_id": self.job_id}]
        text = "".join(e["text"] for e in self._events if e["type"] == "delta")
        if text:
            out.append({"type": "delta", "text": text})
        out.extend(e for e in self._events if e["type"] in TERMINAL)
        return out

    async def stream(self) -> AsyncIterator[dict[str, Any]]:
        """Events from the start of the job (catch-up first), until it ends. Safe to call again after a disconnect."""
        if self.finished:
            for e in self._replay():
                yield e
            return
        q: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        replay = self._replay()
        self._queues.append(q)
        try:
            for e in replay:
                yield e
            while True:
                e = await q.get()
                yield e
                if e["type"] in TERMINAL:
                    return
        finally:
            self._queues.remove(q)


class JobRegistry:
    def __init__(self) -> None:
        self._jobs: dict[BranchId, ReplyJob] = {}
        self._background: set[asyncio.Task[Any]] = set()

    def is_busy(self, branch_id: BranchId) -> bool:
        return branch_id in self._jobs

    def get(self, branch_id: BranchId) -> ReplyJob | None:
        return self._jobs.get(branch_id)

    def start_reply(self, ctx: Ctx, provider: Provider, branch_id: BranchId) -> ReplyJob:
        """Check the reply can be requested, then run it in the background. Errors raise here, before any streaming."""
        if self.is_busy(branch_id):
            raise Busy("A reply is already being generated in this branch.")
        prepared = prepare_reply(ctx, branch_id)
        job = ReplyJob(ctx.env.new_id(), branch_id)
        self._jobs[branch_id] = job
        self._spawn(self._run(ctx, provider, prepared, job))
        return job

    async def _run(self, ctx: Ctx, provider: Provider, prepared: PreparedReply, job: ReplyJob) -> None:
        try:
            await run_reply(ctx, provider, prepared, job.emit)
        finally:
            if not job.finished:
                job.emit({"type": "error", "error": "provider_error", "message": "The reply was interrupted."})
            self._jobs.pop(job.branch_id, None)

    def spawn_background(self, coro: Coroutine[Any, Any, Any]) -> None:
        """Fire-and-forget work such as generated text; a reference is kept so it is not collected early."""
        self._spawn(coro)

    def _spawn(self, coro: Coroutine[Any, Any, Any]) -> None:
        task = asyncio.get_running_loop().create_task(coro)
        self._background.add(task)
        task.add_done_callback(self._background.discard)

    async def drain(self) -> None:
        """Wait for every running job (tests and shutdown)."""
        while self._background:
            await asyncio.gather(*list(self._background), return_exceptions=True)
            await asyncio.sleep(0)  # let finished tasks leave the set; awaiting done tasks alone never yields
