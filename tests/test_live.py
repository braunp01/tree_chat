"""OPTIONAL live check against the real API. It costs real money (a few cents), so it is never part of the default run
and is run only when the owner says so: `uv run pytest -m live` (Req 17.5, design.md Testing Strategy).

At most FIVE short requests in total:
  1-2. two sibling-style requests sharing a long prefix -> the second must read the prefix from the cache;
  3-5. a parent -> child -> grandchild chain, sent with thinking-binding enforcement on, so any change to an earlier
       request prefix (Property 7) would be rejected by the real API.
"""

from __future__ import annotations

import json
import os
from dataclasses import replace
from typing import Any

import pytest

from treechat.domain import context, render
from treechat.domain.model import Role, Settings
from treechat.provider.anthropic_provider import AnthropicProvider, has_credentials

from .builder import Builder

pytestmark = pytest.mark.live

MODEL = os.environ.get("TREECHAT_MODEL", "claude-opus-5-5")
SETTINGS = Settings(model=MODEL, effort="low", max_tokens=1500)
BINDING_BETA = "thinking-binding-controls-2026-08-01"


@pytest.fixture(autouse=True)
def _need_credentials() -> None:
    if not has_credentials():
        pytest.skip("no Anthropic credentials in the environment")


async def _send(p: AnthropicProvider, request: dict[str, Any]) -> Any:
    async def ignore(_: str) -> None:
        return None

    return await p.generate(request, ignore)


def _with_binding(request: dict[str, Any]) -> dict[str, Any]:
    request["thinking"] = {"type": "adaptive", "block_binding": {"prefix_mismatch_behavior": "error"}}
    return request


async def test_sibling_requests_share_a_cached_prefix() -> None:
    p = AnthropicProvider(MODEL, "low")
    long_text = " ".join(f"Sentence {i} about trees, branches and queues." for i in range(1500))  # ~5k tokens
    b = Builder()
    b.add(b.trunk, Role.USER, "Remember the following background text, then answer briefly.")
    a = b.add(b.trunk, Role.ASSISTANT, long_text)
    first = b.spawn(a, 0, 20, intent="first sibling")
    second = b.spawn(a, 0, 20, intent="second sibling")
    b.add(first, Role.USER, "Reply with the single word: one")
    b.add(second, Role.USER, "Reply with the single word: two")
    snap = b.snapshot()
    r1 = await _send(p, render.render(context.assemble(snap, first, SETTINGS), snap.messages))
    r2 = await _send(p, render.render(context.assemble(snap, second, SETTINGS), snap.messages))
    assert r1.usage.get("cache_creation_input_tokens", 0) + r1.usage.get("cache_read_input_tokens", 0) > 0
    assert r2.usage.get("cache_read_input_tokens", 0) > 0, r2.usage  # Req 7.5


async def test_a_deep_chain_replays_signed_thinking_under_enforcement() -> None:
    p = AnthropicProvider(MODEL, "low", extra_betas=(BINDING_BETA,))
    b = Builder()
    b.add(b.trunk, Role.USER, "Name one colour in a single word.")
    reqs: list[dict[str, Any]] = []
    branch = b.trunk
    for depth in range(3):
        snap = b.snapshot()
        request = _with_binding(render.render(context.assemble(snap, branch, SETTINGS), snap.messages))
        reqs.append(json.loads(json.dumps(request)))
        result = await _send(p, request)
        mid = b.add(branch, Role.ASSISTANT, result.text or "ok")
        b.messages = [
            replace(m, blocks_json=json.dumps(list(result.blocks)), model=result.model) if m.id == mid else m
            for m in b.messages
        ]
        if depth < 2:
            branch = b.spawn(mid, 0, max(1, min(3, len(result.text) or 1)), intent=f"level {depth + 1}")
            b.add(branch, Role.USER, "Now name one animal in a single word.")
    assert len(reqs) == 3
    assert reqs[-1]["messages"][1]["role"] == "assistant"  # the earlier reply was replayed to the model
