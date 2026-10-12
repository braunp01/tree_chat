"""Choose the provider named by configuration (tech.md, TREECHAT_PROVIDER)."""

from __future__ import annotations

from treechat.config import Config, ProviderKind
from treechat.provider.anthropic_provider import AnthropicProvider
from treechat.provider.base import Provider
from treechat.provider.fake import FakeProvider


def make_provider(cfg: Config) -> Provider:
    if cfg.provider is ProviderKind.FAKE:
        return FakeProvider()
    return AnthropicProvider(cfg.model, cfg.effort, summary_model=cfg.summary_model)
