"""The provider interface: the only way the app reaches a language model (Req 17)."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Protocol


class ErrorCategory(StrEnum):
    """Matches the error categories in design.md, Error Handling."""

    PROVIDER_ERROR = "provider_error"
    REFUSED = "refused"
    PROVIDER_UNAVAILABLE = "provider_unavailable"
    CONTEXT_TOO_LARGE = "context_too_large"


class ProviderError(Exception):
    def __init__(self, category: ErrorCategory, message: str) -> None:
        super().__init__(message)
        self.category = category
        self.message = message


@dataclass(frozen=True, slots=True)
class ProviderResult:
    """A finished reply. `blocks` are the provider's content blocks as they should be stored and replayed."""

    text: str
    blocks: tuple[dict[str, Any], ...]
    model: str  # the model that actually produced it (a refusal fallback can differ from the requested one)
    stop_reason: str  # "end_turn" or "max_tokens"; refusals are raised, not returned
    usage: dict[str, int] = field(default_factory=lambda: {})


type OnDelta = Callable[[str], Awaitable[None]]


class Provider(Protocol):
    async def generate(self, request: dict[str, Any], on_delta: OnDelta) -> ProviderResult:
        """Stream one reply for a rendered request (domain.render). Raises ProviderError; persists nothing."""
        ...

    async def complete(self, system: str, prompt: str, max_tokens: int) -> str:
        """A short, non-streamed completion for generated descriptions and conclusion drafts (Req 11, 12.1)."""
        ...
