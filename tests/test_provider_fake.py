"""The fake provider and the request-shape rules it enforces (Req 8.4, 8.5, 4.2)."""

from __future__ import annotations

import copy
from typing import Any

import pytest

from treechat.domain import context, render
from treechat.domain.model import TreeSnapshot
from treechat.provider.base import ErrorCategory, ProviderError
from treechat.provider.fake import FakeProvider, RequestShapeError, check_request_shape

from .helpers import SETTINGS, reply
from .helpers import user as user_msg


def req(*turns: dict[str, Any]) -> dict[str, Any]:
    return {"model": "m", "max_tokens": 10, "messages": list(turns)}


def user(text: str = "hi") -> dict[str, Any]:
    return {"role": "user", "content": [{"type": "text", "text": text}]}


def assistant(*blocks: dict[str, Any]) -> dict[str, Any]:
    return {"role": "assistant", "content": list(blocks) or [{"type": "text", "text": "ok"}]}


def system(text: str = "frame") -> dict[str, Any]:
    return {"role": "system", "content": text}


async def collect(p: FakeProvider, request: dict[str, Any]) -> tuple[list[str], Any]:
    deltas: list[str] = []

    async def on_delta(t: str) -> None:
        deltas.append(t)

    result = await p.generate(request, on_delta)
    return deltas, result


@pytest.mark.parametrize(
    "bad",
    [
        req(assistant(), user()),  # does not start with a user turn
        req(user(), user()),  # consecutive user turns
        req(user(), assistant(), assistant(), user()),
        req(system(), user()),  # system first
        req(user(), system(), user()),  # system followed by a user turn
        req(user(), assistant(), system(), assistant(), user()),  # system after an assistant turn
        req(user(), assistant()),  # assistant last: prefill
        req(user(), assistant({"type": "thinking", "thinking": "", "signature": ""}), user()),
        req(
            user(),
            assistant({"type": "thinking", "thinking": "", "signature": "s", "cache_control": {"type": "ephemeral"}}),
            user(),
        ),
        {**req(user()), "temperature": 0.2},
        {**req(user()), "thinking": {"type": "disabled"}},
    ],
)
def test_requests_the_real_api_would_reject_are_rejected(bad: dict[str, Any]) -> None:
    with pytest.raises(RequestShapeError):
        check_request_shape(bad)


def test_a_valid_tangent_shape_is_accepted() -> None:
    check_request_shape(req(user("a"), assistant(), user("b"), system("framing")))
    check_request_shape(req(user("a"), system("framing"), assistant(), user("b")))


def test_too_many_cache_breakpoints_are_rejected() -> None:
    marked = {"type": "text", "text": "x", "cache_control": {"type": "ephemeral"}}
    turns: list[dict[str, Any]] = []
    for _ in range(4):
        turns += [{"role": "user", "content": [dict(marked)]}, assistant()]
    turns.append(user())
    with pytest.raises(RequestShapeError, match="breakpoints"):
        check_request_shape({**req(*turns), "cache_control": {"type": "ephemeral"}})


async def test_replies_are_deterministic_and_stream_in_chunks() -> None:  # Req 8.4
    p = FakeProvider(chunk=5)
    r = req(user("what is a tree"))
    d1, a = await collect(p, r)
    d2, b = await collect(p, copy.deepcopy(r))
    assert a.text == b.text and d1 == d2 and len(d1) > 1 and "".join(d1) == a.text
    _, c = await collect(p, req(user("something else")))
    assert c.text != a.text
    assert a.blocks[0]["type"] == "thinking" and a.blocks[0]["signature"].startswith("fake-sig-")
    assert a.stop_reason == "end_turn" and a.model == "m"


async def test_scripted_outcomes() -> None:
    p = FakeProvider()
    r = req(user("q"))
    p.then("fail", "refuse", "too_large", "truncate", "fallback", "ok")
    with pytest.raises(ProviderError) as e:
        await collect(p, r)
    assert e.value.category is ErrorCategory.PROVIDER_ERROR
    with pytest.raises(ProviderError) as e:
        await collect(p, r)
    assert e.value.category is ErrorCategory.REFUSED
    with pytest.raises(ProviderError) as e:
        await collect(p, r)
    assert e.value.category is ErrorCategory.CONTEXT_TOO_LARGE
    _, cut = await collect(p, r)
    assert cut.stop_reason == "max_tokens"  # Req 3.6
    _, fb = await collect(p, r)
    assert fb.model != "m"  # served by another model
    _, ok = await collect(p, r)
    assert ok.stop_reason == "end_turn"


async def test_unavailable_provider_raises_the_unavailable_category() -> None:  # Req 8.3
    p = FakeProvider()
    p.available = False
    with pytest.raises(ProviderError) as e:
        await collect(p, req(user()))
    assert e.value.category is ErrorCategory.PROVIDER_UNAVAILABLE
    with pytest.raises(ProviderError):
        await p.summarize("s", "p")
    assert p.has_credentials() is False


async def test_summaries_are_deterministic_and_scriptable() -> None:  # Req 9.9, 9.5
    p = FakeProvider()
    prompt = '<conversation>\n<newest role="user">\nWhat about ETag revalidation in caches?\n</newest>\n</conversation>'
    assert (
        await p.summarize("sys", prompt) == await p.summarize("sys", prompt) == "About What about ETag revalidation in."
    )
    assert len(p.summaries) == 2
    p.then_summary("fail", "refuse", "empty")
    for category in (ErrorCategory.PROVIDER_ERROR, ErrorCategory.REFUSED):
        with pytest.raises(ProviderError) as e:
            await p.summarize("sys", prompt)
        assert e.value.category is category
    assert (await p.summarize("sys", prompt)).strip(' ".') == ""


def test_thinking_from_another_model_is_not_replayed() -> None:  # design.md, Thinking replay
    def request_for(model: str) -> dict[str, Any]:
        snap = TreeSnapshot.build(
            [
                user_msg("u1", "T", None, "first", "t1"),
                reply("a1", "T", "u1", "fallback", "t2", model),
                user_msg("u2", "T", "a1", "second", "t3"),
            ]
        )
        r = render.render(context.assemble(snap, "u2", SETTINGS), snap.messages)
        check_request_shape(r)
        return r

    def assistant_block_types(r: dict[str, Any]) -> list[str]:
        return [blk["type"] for t in r["messages"] if t["role"] == "assistant" for blk in t["content"]]

    assert assistant_block_types(request_for("other-model")) == ["text"]
    assert assistant_block_types(request_for(SETTINGS.model)) == ["thinking", "text"]
