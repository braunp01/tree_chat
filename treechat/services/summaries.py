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


def plan_summaries(ctx: Ctx, tree_id: TreeId, skip: Collection[MessageId] = ()) -> list[PreparedSummary]:
    """Req 9.1-9.2, 9.6: the request for every Branch with no Branch_Summary, leaving out `skip`, in graph order.
    One read of the Tree for all of them: a 500-Branch backfill must not reload it per Branch (Req 6.11)."""
    with ctx.store.read() as c:
        _, snap = snapshot(c, tree_id)
        named = repo.summaries_for_tree(c, tree_id)
    out: list[PreparedSummary] = []
    for branch in rules.branches(snap):
        if branch.id in named or branch.id in skip:
            continue
        source = summaries.summary_source(snap, branch)
        system, prompt = summaries.summary_prompt([snap.messages[i] for i in source])
        out.append(PreparedSummary(branch.id, source, system, prompt))
    return out


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
