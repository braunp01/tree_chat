"""The real provider: Anthropic's Messages API through the official SDK (design.md, Provider).

Credentials are read here and nowhere else (Req 17.2). A missing credential never stops the app starting; it only
makes replies fail with `provider_unavailable` (Req 17.3).
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import anthropic

from treechat.provider.base import ErrorCategory, OnDelta, ProviderError, ProviderResult

# Server-side refusal fallback in its "default" form: Anthropic routes a declined request by refusal category.
FALLBACK_BETA = "server-side-fallback-2026-07-01"
_THINKING_TYPES = ("thinking", "redacted_thinking")
_UNAVAILABLE = (
    "No Anthropic credentials found. Set ANTHROPIC_API_KEY in the environment (or run `ant auth login`), "
    "then restart Tree Chat."
)


def has_credentials(env: dict[str, str] | None = None, profile_dir: Path | None = None) -> bool:
    """True if the SDK would find credentials. Never reads or returns their value (Req 17.2)."""
    e = os.environ if env is None else env
    if e.get("ANTHROPIC_API_KEY") or e.get("ANTHROPIC_AUTH_TOKEN"):
        return True
    profiles = profile_dir if profile_dir is not None else Path.home() / ".config" / "anthropic"
    return profiles.is_dir() and any(profiles.iterdir())


def map_error(exc: BaseException) -> ProviderError:
    """Translate an SDK failure into one of the app's error categories (design.md, Error Handling)."""
    if isinstance(exc, ProviderError):
        return exc
    if isinstance(exc, (anthropic.AuthenticationError, anthropic.PermissionDeniedError)):
        return ProviderError(
            ErrorCategory.PROVIDER_UNAVAILABLE, "The provider rejected the credentials. " + _UNAVAILABLE
        )
    if isinstance(exc, anthropic.BadRequestError):
        msg = str(getattr(exc, "message", exc))
        low = msg.lower()
        if "too long" in low or ("exceed" in low and ("context" in low or "token" in low)):
            return ProviderError(ErrorCategory.CONTEXT_TOO_LARGE, "The conversation is too long for the model.")
        return ProviderError(ErrorCategory.PROVIDER_ERROR, f"The provider rejected the request: {msg}")
    if isinstance(exc, anthropic.RateLimitError):
        return ProviderError(ErrorCategory.PROVIDER_ERROR, "The provider is rate limiting requests. Try again shortly.")
    if isinstance(exc, anthropic.APIConnectionError):
        return ProviderError(ErrorCategory.PROVIDER_ERROR, "Could not reach the provider. Check your connection.")
    if isinstance(exc, anthropic.APIStatusError):
        return ProviderError(ErrorCategory.PROVIDER_ERROR, f"The provider failed (HTTP {exc.status_code}).")
    return ProviderError(ErrorCategory.PROVIDER_ERROR, f"The provider failed: {type(exc).__name__}.")


def clean_blocks(blocks: list[dict[str, Any]]) -> tuple[dict[str, Any], ...]:
    """Blocks to store and replay. After a refusal fallback, drop the `fallback` markers and any thinking written
    before the last one (it belongs to the model that declined); everything else is kept exactly as returned."""
    last_fallback = max((i for i, b in enumerate(blocks) if b.get("type") == "fallback"), default=-1)
    return tuple(
        b
        for i, b in enumerate(blocks)
        if b.get("type") != "fallback" and not (b.get("type") in _THINKING_TYPES and i < last_fallback)
    )


class AnthropicProvider:
    def __init__(
        self,
        model: str,
        effort: str,
        client: anthropic.AsyncAnthropic | None = None,
        max_retries: int = 2,
        extra_betas: tuple[str, ...] = (),
    ) -> None:
        self.model = model
        self.effort = effort
        self.max_retries = max_retries
        self.betas = [FALLBACK_BETA, *extra_betas]
        self._injected = client is not None
        self._client = client

    def _get_client(self) -> anthropic.AsyncAnthropic:
        if self._client is None:
            if not has_credentials():
                raise ProviderError(ErrorCategory.PROVIDER_UNAVAILABLE, _UNAVAILABLE)
            self._client = anthropic.AsyncAnthropic(max_retries=self.max_retries)
        return self._client

    async def generate(self, request: dict[str, Any], on_delta: OnDelta) -> ProviderResult:
        client = self._get_client()
        try:
            async with client.beta.messages.stream(**request, betas=self.betas, fallbacks="default") as stream:
                async for text in stream.text_stream:
                    await on_delta(text)
                final = await stream.get_final_message()
        except ProviderError:
            raise
        except anthropic.AnthropicError as exc:
            raise map_error(exc) from exc
        if final.stop_reason == "refusal":
            details = getattr(final, "stop_details", None)
            explanation = getattr(details, "explanation", None)
            raise ProviderError(ErrorCategory.REFUSED, explanation or "The request was declined by the provider.")
        if final.stop_reason not in ("end_turn", "max_tokens"):
            raise ProviderError(ErrorCategory.PROVIDER_ERROR, f"Unexpected stop reason: {final.stop_reason}.")
        raw = [b.model_dump(mode="json", exclude_none=True) for b in final.content]
        blocks = clean_blocks(raw)
        text = "".join(b["text"] for b in blocks if b.get("type") == "text")
        usage = {
            k: int(v)
            for k, v in final.usage.model_dump(mode="json").items()
            if isinstance(v, int) and not isinstance(v, bool)
        }
        return ProviderResult(
            text=text, blocks=blocks, model=str(final.model), stop_reason=str(final.stop_reason), usage=usage
        )

    async def complete(self, system: str, prompt: str, max_tokens: int) -> str:
        client = self._get_client()
        try:
            msg = await client.beta.messages.create(
                model=self.model,
                max_tokens=max(max_tokens, 2000),  # thinking shares the budget on this model
                system=system,
                messages=[{"role": "user", "content": prompt}],
                thinking={"type": "adaptive"},
                output_config={"effort": "low"},
                betas=self.betas,
                fallbacks="default",
            )
        except anthropic.AnthropicError as exc:
            raise map_error(exc) from exc
        if msg.stop_reason == "refusal":
            raise ProviderError(ErrorCategory.REFUSED, "The request was declined by the provider.")
        text = "".join(b.text for b in msg.content if b.type == "text").strip()
        if not text:
            raise ProviderError(ErrorCategory.PROVIDER_ERROR, "The provider returned no text.")
        return text
