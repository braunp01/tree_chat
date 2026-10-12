"""JSON forms of Context_Manifests (Req 4.4). Pure; no database access."""

from __future__ import annotations

import json

from treechat.domain.model import Manifest, MessageEntry, Role


def manifest_to_json(m: Manifest) -> str:
    doc = {
        "system_prompt_version": m.system_prompt_version,
        "model": m.model,
        "settings": {"effort": m.effort, "max_tokens": m.max_tokens},
        "entries": [{"id": e.id, "role": e.role.value} for e in m.entries],
        "cache_breakpoint_after": m.cache_breakpoint_after,
    }
    return json.dumps(doc, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def manifest_from_json(text: str) -> Manifest:
    doc = json.loads(text)
    return Manifest(
        entries=tuple(MessageEntry(e["id"], Role(e["role"])) for e in doc["entries"]),
        model=doc["model"],
        effort=doc["settings"]["effort"],
        max_tokens=doc["settings"]["max_tokens"],
        system_prompt_version=doc["system_prompt_version"],
        cache_breakpoint_after=doc["cache_breakpoint_after"],
    )
