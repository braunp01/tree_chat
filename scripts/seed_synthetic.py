"""Seed a synthetic Tree for the manual readability and speed check (Req 6.11). Spends no AI credits.

    uv run python scripts/seed_synthetic.py data/seed.sqlite3
    $env:TREECHAT_DB="data/seed.sqlite3"; $env:TREECHAT_PROVIDER="fake"; uv run treechat   # PowerShell

Builds one Tree of 500 derived Branches and about 10,700 Messages, written straight to the Store. Every Reply carries
a manifest that is exactly its Path, as a real one would. Synthetic text only. Run it on a Store of its own.
"""

from __future__ import annotations

import json
import random
import sys
from pathlib import Path

from treechat.domain.model import Manifest, Message, MessageEntry, Role
from treechat.store import repo
from treechat.store.codec import manifest_to_json
from treechat.store.db import Store

TREE = "seed-500"
FORKS = 268  # forking mid-run splits a Branch, so this many forks give 500 Branches with seed 7
TURNS_PER_FORK = 20


def main(db: str) -> None:
    store = Store(Path(db))
    rnd = random.Random(7)
    parent: dict[str, str | None] = {}
    assistants: list[str] = []
    tick = 0

    def stamp() -> str:
        nonlocal tick
        tick += 1
        return f"2026-01-01T{tick // 360000:02d}:{(tick // 6000) % 60:02d}:{(tick // 100) % 60:02d}.{tick % 100:06d}Z"

    def path(i: str | None) -> list[str]:
        out: list[str] = []
        while i:
            out.append(i)
            i = parent[i]
        return out[::-1]

    def manifest(ids: list[str]) -> str:
        entries = tuple(MessageEntry(x, Role.USER if k % 2 == 0 else Role.ASSISTANT) for k, x in enumerate(ids))
        breakpoint_after = len(entries) - 2 if len(entries) > 1 else None
        return manifest_to_json(Manifest(entries, "fake", "high", 64000, 2, breakpoint_after))

    with store.transaction() as c:
        repo.create_tree(c, TREE, "Seeded: 500 branches", stamp())
        for fork in range(FORKS):
            at = None if fork == 0 else rnd.choice(assistants)
            for k in range(TURNS_PER_FORK):
                for role in (Role.USER, Role.ASSISTANT):
                    mid = f"seed{len(parent):06d}"
                    parent[mid] = at
                    if role is Role.USER:
                        text = f"Question {fork}.{k}: " + "lorem ipsum " * rnd.randint(1, 8)
                        repo.insert_message(c, Message(mid, TREE, at, role, text, None, None, None, stamp()))
                    else:
                        text = f"Reply {fork}.{k}. " + "Some *markdown* text. " * rnd.randint(2, 30)
                        blocks = json.dumps([{"type": "text", "text": text}])
                        m = Message(mid, TREE, at, role, text, blocks, "fake", "end_turn", stamp())
                        repo.insert_message(c, m, manifest(path(at)))
                        assistants.append(mid)
                    at = mid
        repo.touch_tree(c, TREE, stamp())
    print(f"Tree {TREE}: {len(parent)} messages in {db}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "data/seed.sqlite3")
