"""Synthetic data for tests (no real conversations), a counting clock and id source, and a fake-provider context."""

from __future__ import annotations

import itertools
import json
from pathlib import Path

from treechat.domain.model import Manifest, Message, MessageEntry, Role, Settings
from treechat.env import Env
from treechat.services.ctx import Ctx
from treechat.store.codec import manifest_to_json
from treechat.store.db import Store

SETTINGS = Settings(model="fake-model", effort="high", max_tokens=1000)


def counting_env() -> Env:
    n = itertools.count(1)
    return Env(now=lambda: f"t{next(n):08d}", new_id=lambda: f"id{next(n):08d}")


def make_ctx(path: Path) -> Ctx:
    return Ctx(Store(path / "test.sqlite3"), counting_env(), SETTINGS)


def user(mid: str, tree: str, parent: str | None, text: str = "a question", at: str = "t0") -> Message:
    return Message(mid, tree, parent, Role.USER, text, created_at=at)


def reply(
    mid: str, tree: str, parent: str, text: str = "an answer", at: str = "t0", model: str = "fake-model"
) -> Message:
    blocks = json.dumps(
        [{"type": "thinking", "thinking": "", "signature": f"sig-{mid}"}, {"type": "text", "text": text}]
    )
    return Message(
        mid, tree, parent, Role.ASSISTANT, text, blocks_json=blocks, model=model, stop_reason="end_turn", created_at=at
    )


def manifest_json(*ids: str) -> str:
    entries = tuple(MessageEntry(i, Role.USER if k % 2 == 0 else Role.ASSISTANT) for k, i in enumerate(ids))
    return manifest_to_json(
        Manifest(entries, "fake-model", "high", 1000, 2, len(entries) - 2 if len(entries) > 1 else None)
    )
