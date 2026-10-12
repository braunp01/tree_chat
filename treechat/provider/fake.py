"""A deterministic offline provider. Every automated test uses it, so tests spend no AI credits (Req 8.4, 8.5).

It also checks each request against the rules the real API enforces, so a rendering mistake fails a test here
instead of failing a paid request later.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
from collections import deque
from typing import Any, cast

from treechat.provider.base import ErrorCategory, OnDelta, ProviderError, ProviderResult

FAKE_MODEL_SUFFIX = "-fake"
FAKE_SUMMARY_MODEL = "fake-summary-model"


class RequestShapeError(AssertionError):
    """The request would be rejected by the real API."""


def check_request_shape(request: dict[str, Any]) -> None:
    messages: list[dict[str, Any]] = request["messages"]
    if not messages or messages[0]["role"] != "user":
        raise RequestShapeError("the first message must be a user turn")
    if messages[-1]["role"] == "assistant":
        raise RequestShapeError("the last turn must not be an assistant turn (prefill is rejected on this model)")
    marks = 0
    for i, turn in enumerate(messages):
        role = turn["role"]
        if role not in ("user", "assistant", "system"):
            raise RequestShapeError(f"unknown role {role!r}")
        if i and role == messages[i - 1]["role"] and role != "system":
            raise RequestShapeError(f"two consecutive {role} turns at {i}")
        if role == "system":
            if i == 0 or messages[i - 1]["role"] != "user":
                raise RequestShapeError("a system message must follow a user turn")
            if i + 1 < len(messages) and messages[i + 1]["role"] != "assistant":
                raise RequestShapeError("a system message must be last or followed by an assistant turn")
            if not isinstance(turn["content"], str) or not turn["content"]:
                raise RequestShapeError("a system message needs text content")
            continue
        blocks: Any = turn["content"]
        if not isinstance(blocks, list) or not blocks:
            raise RequestShapeError(f"turn {i} needs a non-empty block list")
        for blk in cast(list[dict[str, Any]], blocks):
            if blk["type"] == "thinking" and not blk.get("signature"):
                raise RequestShapeError("a replayed thinking block lost its signature")
            if "cache_control" in blk:
                marks += 1
                if blk["type"] in ("thinking", "redacted_thinking"):
                    raise RequestShapeError("cache_control on a thinking block")
    if marks + (1 if "cache_control" in request else 0) > 4:
        raise RequestShapeError("more than 4 cache breakpoints")
    if request.get("thinking", {}).get("type") not in (None, "adaptive"):
        raise RequestShapeError("only adaptive thinking is accepted on this model")
    if "temperature" in request or "top_p" in request or "top_k" in request:
        raise RequestShapeError("sampling parameters are rejected on this model")


def _last_user_text(request: dict[str, Any]) -> str:
    for turn in reversed(request["messages"]):
        if turn["role"] == "user":
            return " ".join(b["text"] for b in turn["content"] if b["type"] == "text")
    return ""


class FakeProvider:
    """Replies depend only on the request bytes, so identical requests give identical replies."""

    def __init__(self, chunk: int = 7) -> None:
        self.chunk = chunk
        self.requests: list[dict[str, Any]] = []
        self.summaries: list[tuple[str, str]] = []
        self.summary_gate: asyncio.Event | None = None  # when set, summarize() waits for it (to test pending labels)
        self._summary_script: deque[str] = deque()
        self.gate: asyncio.Event | None = None  # when set, generate() waits for it (to test `busy`, disconnects)
        self._script: deque[str] = deque()
        self.available = True

    # -- test controls --------------------------------------------------------------------------
    def then(self, *outcomes: str) -> None:
        """Queue outcomes for the next calls: "ok", "fail", "refuse", "truncate", "fallback", "too_large"."""
        self._script.extend(outcomes)

    def then_summary(self, *outcomes: str) -> None:
        """Queue outcomes for the next summaries: "ok", "fail", "refuse", "empty" (Req 9.5)."""
        self._summary_script.extend(outcomes)

    # -- Provider -------------------------------------------------------------------------------
    async def generate(self, request: dict[str, Any], on_delta: OnDelta) -> ProviderResult:
        check_request_shape(request)
        self.requests.append(json.loads(json.dumps(request)))
        if not self.available:
            raise ProviderError(ErrorCategory.PROVIDER_UNAVAILABLE, "No credentials: set ANTHROPIC_API_KEY.")
        outcome = self._script.popleft() if self._script else "ok"
        digest = hashlib.sha256(json.dumps(request, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:12]
        quote = _last_user_text(request).strip().replace("\n", " ")[:60]
        text = f"Fake reply {digest} to: {quote}"
        if outcome == "truncate":
            text = text[: len(text) // 2]
        if outcome == "too_large":
            raise ProviderError(ErrorCategory.CONTEXT_TOO_LARGE, "The conversation is too long for the model.")
        if self.gate is not None:
            await self.gate.wait()
        if outcome == "fail":
            await on_delta("partial ")
            raise ProviderError(ErrorCategory.PROVIDER_ERROR, "The provider failed.")
        for i in range(0, len(text), self.chunk):
            await on_delta(text[i : i + self.chunk])
            await asyncio.sleep(0)
        if outcome == "refuse":
            raise ProviderError(ErrorCategory.REFUSED, "The request was declined.")
        model = request["model"] + (FAKE_MODEL_SUFFIX if outcome == "fallback" else "")
        blocks: tuple[dict[str, Any], ...] = (
            {"type": "thinking", "thinking": "", "signature": f"fake-sig-{digest}"},
            {"type": "text", "text": text},
        )
        return ProviderResult(
            text=text,
            blocks=blocks,
            model=model,
            stop_reason="max_tokens" if outcome == "truncate" else "end_turn",
            usage={"input_tokens": 1, "output_tokens": len(text) // 4 + 1},
        )

    @property
    def summary_model(self) -> str:
        return FAKE_SUMMARY_MODEL

    def has_credentials(self) -> bool:
        return self.available

    async def summarize(self, system: str, prompt: str) -> str:
        """Req 9.9: deterministic, offline. Names the part of the conversation after its newest Message."""
        self.summaries.append((system, prompt))
        if not self.available:
            raise ProviderError(ErrorCategory.PROVIDER_UNAVAILABLE, "No credentials: set ANTHROPIC_API_KEY.")
        outcome = self._summary_script.popleft() if self._summary_script else "ok"
        if self.summary_gate is not None:
            await self.summary_gate.wait()
        if outcome == "fail":
            raise ProviderError(ErrorCategory.PROVIDER_ERROR, "The provider failed.")
        if outcome == "refuse":
            raise ProviderError(ErrorCategory.REFUSED, "The request was declined by the provider.")
        if outcome == "empty":
            return '  "".  '
        m = re.search(r"<newest [^>]*>\n(.*?)\n</newest>", prompt, re.S)
        words = (m.group(1) if m else prompt).split()[:5]
        return f"About {' '.join(words)}." if words else "About nothing much."
