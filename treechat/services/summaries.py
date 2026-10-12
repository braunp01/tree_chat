"""Branch_Summaries (Req 9): which Branches need one, what each is written from, and saving the result.

One transaction per operation; the provider is called by `jobs.summaries`, not here.
"""

from __future__ import annotations

from collections.abc import Collection
from dataclasses import dataclass

from treechat.domain import rules, summaries
from treechat.domain.model import MessageId, TreeId
from treechat.services.ctx import Ctx
from treechat.services.trees import snapshot
from treechat.store import repo


@dataclass(frozen=True, slots=True)
class PreparedSummary:
    message_id: MessageId  # the Branch's first Message
    source: tuple[MessageId, ...]
    system: str
    prompt: str


def unnamed_branches(ctx: Ctx, tree_id: TreeId, skip: Collection[MessageId] = ()) -> list[MessageId]:
    """Req 9.1, 9.6: Branch starts with no Branch_Summary, in graph order, leaving out `skip`."""
    with ctx.store.read() as c:
        _, snap = snapshot(c, tree_id)
        named = repo.summaries_for_tree(c, tree_id)
    return [s for s in summaries.branch_starts(snap) if s not in named and s not in skip]


def prepare_summary(ctx: Ctx, tree_id: TreeId, start: MessageId) -> PreparedSummary | None:
    """Req 9.2: the request for one Branch, from the Store as it is now. None if it no longer needs one."""
    with ctx.store.read() as c:
        _, snap = snapshot(c, tree_id)
        if start in repo.summaries_for_tree(c, tree_id):
            return None
    branch = next((b for b in rules.branches(snap) if b.id == start), None)
    if branch is None:
        return None
    source = summaries.summary_source(snap, branch)
    system, prompt = summaries.summary_prompt([snap.messages[i] for i in source])
    return PreparedSummary(start, source, system, prompt)


def save_summary(ctx: Ctx, prepared: PreparedSummary, text: str, model: str) -> str | None:
    """Req 9.3, 9.5: clean the model's answer and keep it, with what it was written from. None if nothing usable."""
    name = summaries.clean_summary(text)
    if name is None:
        return None
    row = repo.SummaryRow(
        prepared.message_id, name, model, prepared.source, summaries.SUMMARY_PROMPT_VERSION, ctx.env.now()
    )
    with ctx.store.transaction() as c:
        repo.insert_summary(c, row)
    return name
