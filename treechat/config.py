"""Settings read from the environment once at start-up (tech.md, Settings and environment variables)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path


class ProviderKind(StrEnum):
    ANTHROPIC = "anthropic"
    FAKE = "fake"


@dataclass(frozen=True, slots=True)
class Config:
    db_path: Path
    port: int
    model: str
    effort: str
    nudge_after: int
    provider: ProviderKind


def load_config(env: dict[str, str] | None = None) -> Config:
    e = os.environ if env is None else env
    return Config(
        db_path=Path(e.get("TREECHAT_DB", "data/tree_chat.sqlite3")),
        port=int(e.get("TREECHAT_PORT", "8765")),
        model=e.get("TREECHAT_MODEL", "claude-opus-5-5"),
        effort=e.get("TREECHAT_EFFORT", "high"),
        nudge_after=int(e.get("TREECHAT_NUDGE_AFTER", "8")),
        provider=ProviderKind(e.get("TREECHAT_PROVIDER", "anthropic")),
    )
