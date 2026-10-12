"""Background jobs that name Branches (Req 9). The only other caller of the provider besides replies.

`ensure(tree)` runs after every send and whenever a Tree's shape is served (design.md, Branch summaries: when).
Each Branch is tried at most once per run of the server, and at most two jobs call the model at a time.
"""

from __future__ import annotations

import asyncio
import logging

from treechat.domain.model import MessageId, TreeId
from treechat.jobs.registry import JobRegistry
from treechat.provider.base import Provider, ProviderError
from treechat.services import summaries
from treechat.services.ctx import Ctx

log = logging.getLogger("treechat.jobs")

AT_ONCE = 2


class SummaryJobs:
    def __init__(self, ctx: Ctx, provider: Provider, registry: JobRegistry, at_once: int = AT_ONCE) -> None:
        self.ctx = ctx
        self.provider = provider
        self.registry = registry
        self.at_once = at_once
        self.attempted: set[MessageId] = set()  # Req 9.6: once per Branch per run
        self._running: set[MessageId] = set()
        self._limit: tuple[asyncio.AbstractEventLoop, asyncio.Semaphore] | None = None

    def pending(self) -> frozenset[MessageId]:
        """Branch starts whose summary is being written now (`summary_pending`, Req 9.4)."""
        return frozenset(self._running)

    def ensure(self, tree_id: TreeId) -> None:
        """Req 9.1, 9.6, 9.8: start a job for each unnamed Branch not yet tried. Call from a running event loop."""
        if not self.provider.has_credentials():
            return
        for prepared in summaries.plan_summaries(self.ctx, tree_id, skip=self.attempted):
            self.attempted.add(prepared.message_id)
            self._running.add(prepared.message_id)
            self.registry.spawn_background(self._run(prepared))

    def _semaphore(self) -> asyncio.Semaphore:
        loop = asyncio.get_running_loop()
        if self._limit is None or self._limit[0] is not loop:
            self._limit = (loop, asyncio.Semaphore(self.at_once))
        return self._limit[1]

    async def _run(self, prepared: summaries.PreparedSummary) -> None:
        try:
            async with self._semaphore():
                await self._name(prepared)
        except Exception:  # a bug must not take the server down; the node keeps its fallback label
            log.exception("naming a branch failed")
        finally:
            self._running.discard(prepared.message_id)

    async def _name(self, prepared: summaries.PreparedSummary) -> None:
        """Only the model call and one insert happen here; the Tree was read once, by `ensure`."""
        try:
            text = await self.provider.summarize(prepared.system, prepared.prompt)
        except ProviderError as exc:  # Req 9.5: nothing persisted, no error shown; only the category is logged
            log.info("branch summary not written: %s", exc.category.value)
            return
        # The write goes to a worker thread: a backfill of hundreds must not hold up requests (Req 6.11).
        saved = await asyncio.to_thread(summaries.save_summary, self.ctx, prepared, text, self.provider.summary_model)
        if saved is None:
            log.info("branch summary not written: empty answer")
