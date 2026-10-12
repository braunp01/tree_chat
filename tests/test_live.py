"""OPTIONAL live check against the real API. It costs real money (a few cents), so it is never part of the default run
and is run only when the owner says so: `uv run pytest -m live` (Req 8.5, design.md Testing Strategy).

At most SIX short requests in total:
  1-2. two sibling-style requests sharing a long prefix -> the second must read the prefix from the cache;
  3-5. a three-reply path, sent with thinking-binding enforcement on, so any change to an earlier request prefix
       (Property 5) would be rejected by the real API;
  6.   one Branch_Summary on Claude Haiku 5.5 (Req 9), a fraction of a cent.
"""

from __future__ import annotations

import json
import os
from dataclasses import replace
from typing import Any

import pytest

from treechat.domain import context, render, summaries
from treechat.domain.model import Message, Role, Settings, TreeSnapshot
from treechat.provider.anthropic_provider import AnthropicProvider, has_credentials

from .helpers import reply, user

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


def _snap(msgs: list[Message]) -> TreeSnapshot:
    return TreeSnapshot.build(msgs)


async def test_sibling_requests_share_a_cached_prefix() -> None:
    p = AnthropicProvider(MODEL, "low")
    long_text = " ".join(f"Sentence {i} about trees, branches and forks." for i in range(1500))  # ~5k tokens
    base = [
        user("u1", "L", None, "Remember the following background text, then answer briefly.", "t1"),
        reply("a1", "L", "u1", long_text, "t2", MODEL),
    ]
    base[1] = replace(base[1], blocks_json=json.dumps([{"type": "text", "text": long_text}]))
    snap = _snap(
        [
            *base,
            user("x", "L", "a1", "Reply with the single word: one", "t3"),
            user("y", "L", "a1", "Reply with the single word: two", "t4"),
        ]
    )  # two branches from a1
    r1 = await _send(p, render.render(context.assemble(snap, "x", SETTINGS), snap.messages))
    r2 = await _send(p, render.render(context.assemble(snap, "y", SETTINGS), snap.messages))
    assert r1.usage.get("cache_creation_input_tokens", 0) + r1.usage.get("cache_read_input_tokens", 0) > 0
    assert r2.usage.get("cache_read_input_tokens", 0) > 0, r2.usage  # Req 4.3


async def test_a_deep_path_replays_signed_thinking_under_enforcement() -> None:
    p = AnthropicProvider(MODEL, "low", extra_betas=(BINDING_BETA,))
    msgs: list[Message] = [user("u0", "L", None, "Name one colour in a single word.", "t0")]
    reqs: list[dict[str, Any]] = []
    for depth in range(3):
        snap = _snap(msgs)
        uid = msgs[-1].id
        request = _with_binding(render.render(context.assemble(snap, uid, SETTINGS), snap.messages))
        reqs.append(json.loads(json.dumps(request)))
        result = await _send(p, request)
        aid = f"a{depth}"
        msgs.append(
            Message(
                aid,
                "L",
                uid,
                Role.ASSISTANT,
                result.text or "ok",
                json.dumps(list(result.blocks)),
                result.model,
                result.stop_reason,
                f"t{depth}a",
            )
        )
        if depth < 2:
            msgs.append(user(f"u{depth + 1}", "L", aid, "Now name one animal in a single word.", f"t{depth}b"))
    assert len(reqs) == 3
    assert reqs[-1]["messages"][1]["role"] == "assistant"  # the earlier reply was replayed to the model


async def test_a_branch_summary_from_haiku_fits_a_node() -> None:  # Req 9.2, 9.5 (request 6)
    p = AnthropicProvider(MODEL, "low", summary_model=os.environ.get("TREECHAT_SUMMARY_MODEL", "claude-haiku-5-5"))
    msgs = [
        user("u1", "L", None, "How do HTTP caches decide whether a stored response is still fresh?", "t1"),
        reply("a1", "L", "u1", "They compare its age with max-age or Expires.", "t2", MODEL),
        user("u2", "L", "a1", "And what does the Vary header change about that?", "t3"),
    ]
    system, prompt = summaries.summary_prompt(msgs)
    name = summaries.clean_summary(await p.summarize(system, prompt))
    assert name is not None and 1 <= len(name.split()) <= 8 and len(name) <= 60
