"""JSON forms of Context_Manifests (Req 7.7). Pure; no database access."""

from __future__ import annotations

import json
from typing import Any

from treechat.domain.model import Entry, FramingEntry, Manifest, MessageEntry, Role


def manifest_to_json(m: Manifest) -> str:
    entries: list[dict[str, Any]] = []
    for e in m.entries:
        if isinstance(e, FramingEntry):
            entries.append({"kind": "framing", "branch_id": e.branch_id, "text": e.text})
        else:
            entries.append({"kind": "message", "id": e.id, "role": e.role.value})
    doc = {
        "system_prompt_version": m.system_prompt_version,
        "model": m.model,
        "settings": {"effort": m.effort, "max_tokens": m.max_tokens},
        "entries": entries,
        "cache_breakpoint_after": m.cache_breakpoint_after,
    }
    return json.dumps(doc, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def manifest_from_json(text: str) -> Manifest:
    doc = json.loads(text)
    entries: list[Entry] = []
    for e in doc["entries"]:
        if e["kind"] == "framing":
            entries.append(FramingEntry(e["branch_id"], e["text"]))
        else:
            entries.append(MessageEntry(e["id"], Role(e["role"])))
    return Manifest(
        entries=tuple(entries),
        model=doc["model"],
        effort=doc["settings"]["effort"],
        max_tokens=doc["settings"]["max_tokens"],
        system_prompt_version=doc["system_prompt_version"],
        cache_breakpoint_after=doc["cache_breakpoint_after"],
    )
