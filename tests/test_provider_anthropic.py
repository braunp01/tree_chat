"""The Anthropic adapter, run through the real SDK against canned HTTP responses. No network, no credits
(Req 17.1-17.3, 2.2-2.4, 7.10; design.md Provider)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import anthropic
import httpx2
import pytest

from treechat.provider import anthropic_provider as ap
from treechat.provider.anthropic_provider import AnthropicProvider, clean_blocks, has_credentials
from treechat.provider.base import ErrorCategory, ProviderError

REQUEST: dict[str, Any] = {
    "model": "claude-opus-5-5",
    "max_tokens": 1000,
    "system": [{"type": "text", "text": "frozen"}],
    "messages": [
        {"role": "user", "content": [{"type": "text", "text": "hello", "cache_control": {"type": "ephemeral"}}]},
        {"role": "system", "content": "frame"},
    ],
    "thinking": {"type": "adaptive"},
    "output_config": {"effort": "high"},
    "cache_control": {"type": "ephemeral"},
}


def sse(*events: tuple[str, dict[str, Any]]) -> bytes:
    return "".join(f"event: {name}\ndata: {json.dumps(data)}\n\n" for name, data in events).encode()


def message_events(
    blocks: list[dict[str, Any]],
    stop_reason: str = "end_turn",
    model: str = "claude-opus-5-5",
    usage: dict[str, int] | None = None,
) -> bytes:
    """A full streamed message: each block is a dict with `type` and either `text` pieces or a `signature`."""
    events: list[tuple[str, dict[str, Any]]] = [
        (
            "message_start",
            {
                "type": "message_start",
                "message": {
                    "id": "msg_1",
                    "type": "message",
                    "role": "assistant",
                    "model": model,
                    "content": [],
                    "stop_reason": None,
                    "stop_sequence": None,
                    "usage": usage or {"input_tokens": 10, "output_tokens": 1},
                },
            },
        )
    ]
    for i, blk in enumerate(blocks):
        kind = blk["type"]
        if kind == "thinking":
            events.append(
                (
                    "content_block_start",
                    {
                        "type": "content_block_start",
                        "index": i,
                        "content_block": {"type": "thinking", "thinking": "", "signature": ""},
                    },
                )
            )
            events.append(
                (
                    "content_block_delta",
                    {
                        "type": "content_block_delta",
                        "index": i,
                        "delta": {"type": "signature_delta", "signature": blk["signature"]},
                    },
                )
            )
        elif kind == "text":
            events.append(
                (
                    "content_block_start",
                    {"type": "content_block_start", "index": i, "content_block": {"type": "text", "text": ""}},
                )
            )
            for piece in blk["pieces"]:
                events.append(
                    (
                        "content_block_delta",
                        {"type": "content_block_delta", "index": i, "delta": {"type": "text_delta", "text": piece}},
                    )
                )
        else:  # fallback marker
            events.append(("content_block_start", {"type": "content_block_start", "index": i, "content_block": blk}))
        events.append(("content_block_stop", {"type": "content_block_stop", "index": i}))
    events.append(
        (
            "message_delta",
            {
                "type": "message_delta",
                "delta": {"stop_reason": stop_reason, "stop_sequence": None},
                "usage": {"output_tokens": 12},
            },
        )
    )
    events.append(("message_stop", {"type": "message_stop"}))
    return sse(*events)


class Wire:
    """Captures what the SDK sent and answers with canned bytes."""

    def __init__(self, status: int = 200, body: bytes = b"", content_type: str = "text/event-stream") -> None:
        self.status, self.body, self.content_type = status, body, content_type
        self.requests: list[httpx2.Request] = []

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        return httpx2.Response(self.status, headers={"content-type": self.content_type}, content=self.body)


def provider(wire: Any, retries: int = 0) -> AnthropicProvider:
    client = anthropic.AsyncAnthropic(
        api_key="test-key-not-real",
        max_retries=retries,
        http_client=anthropic.DefaultAsyncHttpxClient(transport=httpx2.MockTransport(wire)),
    )
    return AnthropicProvider("claude-opus-5-5", "high", client=client)


async def run(p: AnthropicProvider) -> tuple[list[str], Any]:
    deltas: list[str] = []

    async def on_delta(t: str) -> None:
        deltas.append(t)

    return deltas, await p.generate(json.loads(json.dumps(REQUEST)), on_delta)


GOOD = message_events(
    [{"type": "thinking", "signature": "sigABC"}, {"type": "text", "pieces": ["Hel", "lo ", "there"]}],
    usage={"input_tokens": 10, "output_tokens": 1, "cache_read_input_tokens": 700, "cache_creation_input_tokens": 50},
)


async def test_the_request_carries_every_setting_the_design_requires() -> None:  # design.md Provider, Prompt caching
    wire = Wire(body=GOOD)
    await run(provider(wire))
    (sent,) = wire.requests
    assert sent.url.path == "/v1/messages"
    assert ap.FALLBACK_BETA in sent.headers["anthropic-beta"]
    body = json.loads(sent.content)
    assert body["model"] == "claude-opus-5-5" and body["stream"] is True
    assert body["fallbacks"] == "default"
    assert body["thinking"] == {"type": "adaptive"} and body["output_config"] == {"effort": "high"}
    assert body["cache_control"] == {"type": "ephemeral"}
    assert body["messages"][1] == {"role": "system", "content": "frame"}
    assert body["messages"][0]["content"][0]["cache_control"] == {"type": "ephemeral"}
    assert sent.headers["x-api-key"] == "test-key-not-real"
    assert "temperature" not in body


async def test_text_streams_in_order_and_the_result_keeps_signed_thinking() -> None:  # Req 2.2
    deltas, result = await run(provider(Wire(body=GOOD)))
    assert deltas == ["Hel", "lo ", "there"]
    assert result.text == "Hello there" and result.stop_reason == "end_turn" and result.model == "claude-opus-5-5"
    assert [b["type"] for b in result.blocks] == ["thinking", "text"]
    assert result.blocks[0]["signature"] == "sigABC"
    assert all(v is not None for b in result.blocks for v in b.values())  # stored without null fields
    assert result.usage["cache_read_input_tokens"] == 700


async def test_a_reply_cut_off_at_max_tokens_is_returned_not_raised() -> None:  # Req 2.4
    body = message_events([{"type": "text", "pieces": ["partial"]}], stop_reason="max_tokens")
    _, result = await run(provider(Wire(body=body)))
    assert result.stop_reason == "max_tokens" and result.text == "partial"


async def test_a_refusal_raises_the_refused_category() -> None:  # Req 2.3
    body = message_events([], stop_reason="refusal")
    with pytest.raises(ProviderError) as e:
        await run(provider(Wire(body=body)))
    assert e.value.category is ErrorCategory.REFUSED


async def test_a_reply_served_by_the_fallback_model_is_cleaned_and_attributed() -> None:
    body = message_events(
        [
            {"type": "thinking", "signature": "declined-model-sig"},
            {"type": "fallback", "from": {"model": "claude-opus-5-5"}, "to": {"model": "claude-opus-4-8"}},
            {"type": "text", "pieces": ["Served by the fallback"]},
        ],
        model="claude-opus-4-8",
    )
    _, result = await run(provider(Wire(body=body)))
    assert result.model == "claude-opus-4-8"
    assert [b["type"] for b in result.blocks] == ["text"]


def test_clean_blocks_keeps_everything_when_no_fallback_happened() -> None:
    blocks = [{"type": "thinking", "signature": "s"}, {"type": "text", "text": "t"}]
    assert clean_blocks(blocks) == tuple(blocks)
    after = [
        {"type": "thinking", "signature": "old"},
        {"type": "text", "text": "partial"},
        {"type": "fallback"},
        {"type": "thinking", "signature": "new"},
        {"type": "text", "text": "rest"},
    ]
    assert [b.get("signature") or b["text"] for b in clean_blocks(after)] == ["partial", "new", "rest"]


@pytest.mark.parametrize(
    "status,message,category",
    [
        (401, "invalid x-api-key", ErrorCategory.PROVIDER_UNAVAILABLE),
        (403, "forbidden", ErrorCategory.PROVIDER_UNAVAILABLE),
        (400, "prompt is too long: 300000 tokens > 200000 maximum", ErrorCategory.CONTEXT_TOO_LARGE),
        (400, "input length and max_tokens exceed context limit", ErrorCategory.CONTEXT_TOO_LARGE),
        (400, "messages: roles must alternate", ErrorCategory.PROVIDER_ERROR),
        (429, "rate limited", ErrorCategory.PROVIDER_ERROR),
        (500, "internal error", ErrorCategory.PROVIDER_ERROR),
        (529, "overloaded", ErrorCategory.PROVIDER_ERROR),
    ],
)
async def test_http_failures_map_to_error_categories(status: int, message: str, category: ErrorCategory) -> None:
    kinds = {
        400: "invalid_request_error",
        401: "authentication_error",
        403: "permission_error",
        429: "rate_limit_error",
    }
    err = {"type": "error", "error": {"type": kinds.get(status, "api_error"), "message": message}}
    wire = Wire(status=status, body=json.dumps(err).encode(), content_type="application/json")
    with pytest.raises(ProviderError) as e:
        await run(provider(wire))
    assert e.value.category is category
    assert "test-key-not-real" not in e.value.message  # Req 17.2: no secrets in errors


async def test_a_dropped_connection_is_a_provider_error() -> None:
    def refuse(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("no route", request=request)

    with pytest.raises(ProviderError) as e:
        await run(provider(refuse))
    assert e.value.category is ErrorCategory.PROVIDER_ERROR


async def test_without_credentials_no_request_is_made(monkeypatch: pytest.MonkeyPatch) -> None:  # Req 17.3
    monkeypatch.setattr(ap, "has_credentials", lambda *a, **k: False)
    p = AnthropicProvider("claude-opus-5-5", "high")  # builds its own client lazily
    with pytest.raises(ProviderError) as e:
        await run(p)
    assert e.value.category is ErrorCategory.PROVIDER_UNAVAILABLE and "ANTHROPIC_API_KEY" in e.value.message
    with pytest.raises(ProviderError):
        await p.complete("s", "p", 10)


def test_credential_detection_never_reads_values(tmp_path: Path) -> None:
    empty = tmp_path / "none"
    assert not has_credentials({}, empty)
    assert has_credentials({"ANTHROPIC_API_KEY": "x"}, empty)
    assert has_credentials({"ANTHROPIC_AUTH_TOKEN": "x"}, empty)
    profiles = tmp_path / "profiles"
    profiles.mkdir()
    assert not has_credentials({}, profiles)
    (profiles / "default.json").write_text("{}")
    assert has_credentials({}, profiles)


async def test_complete_returns_plain_text_and_uses_low_effort() -> None:  # Req 11.1, 12.1
    msg = {
        "id": "msg_2",
        "type": "message",
        "role": "assistant",
        "model": "claude-opus-5-5",
        "content": [{"type": "text", "text": "  A short summary.  "}],
        "stop_reason": "end_turn",
        "stop_sequence": None,
        "usage": {"input_tokens": 5, "output_tokens": 5},
    }
    wire = Wire(body=json.dumps(msg).encode(), content_type="application/json")
    out = await provider(wire).complete("system text", "summarise this", 100)
    assert out == "A short summary."
    body = json.loads(wire.requests[0].content)
    assert body["output_config"] == {"effort": "low"} and body["max_tokens"] >= 2000
    assert body["system"] == "system text" and "stream" not in body


async def test_complete_rejects_an_empty_answer() -> None:
    msg = {
        "id": "m",
        "type": "message",
        "role": "assistant",
        "model": "x",
        "content": [],
        "stop_reason": "end_turn",
        "stop_sequence": None,
        "usage": {"input_tokens": 1, "output_tokens": 0},
    }
    wire = Wire(body=json.dumps(msg).encode(), content_type="application/json")
    with pytest.raises(ProviderError):
        await provider(wire).complete("s", "p", 10)


def test_nothing_in_the_default_run_can_reach_the_real_api() -> None:  # Req 17.5
    import socket

    s = socket.socket()
    try:
        with pytest.raises(RuntimeError, match="Req 17.5"):
            s.connect(("api.anthropic.com", 443))
    finally:
        s.close()
