"""Branch_Summaries: what each one is written from, the frozen request text, and cleaning the answer (Req 9). Pure.

A summary never enters a Reply's Context (Req 9.7): nothing in `context` or `render` reads this module.
"""

from __future__ import annotations

from treechat.domain import rules
from treechat.domain.model import BranchInfo, Message, MessageId, Role, TreeSnapshot

SUMMARY_PROMPT_VERSION = 1
SOURCE_SIZE = 5  # Req 9.2: the five most recent Messages
CLIP = 4_000  # characters of each Message sent; the name needs the gist (design.md, Branch summaries: source)
MAX_WORDS = 8
MAX_CHARS = 60  # the Store's limit

# Frozen: changing it means a new SUMMARY_PROMPT_VERSION.
SUMMARY_SYSTEM_V1 = (
    "You name parts of a conversation for a map of it. Answer with a name of five or six words that says what this "
    "part of the conversation is about, giving the most weight to the newest message. Answer with the name only: "
    "no quotes, no full stop, nothing else."
)


def branch_starts(snap: TreeSnapshot) -> tuple[MessageId, ...]:
    """Req 9.1: the first Message of every Branch, which is what a summary is stored against."""
    return tuple(b.id for b in rules.branches(snap))


def summary_source(snap: TreeSnapshot, branch: BranchInfo) -> tuple[MessageId, ...]:
    """Glossary Summary_Source: the last five Messages of the Path to the Branch's last Message, oldest first."""
    return rules.path(snap, branch.message_ids[-1])[-SOURCE_SIZE:]


def summary_prompt(messages: list[Message]) -> tuple[str, str]:
    """Req 9.2: the system text and the prompt for one summary. Same Messages, same bytes."""
    lines = ["<conversation>"]
    for i, m in enumerate(messages):
        tag = "newest" if i == len(messages) - 1 else "message"
        who = "user" if m.role is Role.USER else "assistant"
        lines.append(f'<{tag} role="{who}">\n{m.content[:CLIP]}\n</{tag}>')
    lines.append("</conversation>")
    lines.append("Name this part of the conversation in five or six words, weighted towards the newest message.")
    return SUMMARY_SYSTEM_V1, "\n".join(lines)


_EDGE = " \t\"'`*_#“”‘’«»"
_TRAILING = ".!?:;,"


def clean_summary(text: str) -> str | None:
    """Req 9.5: one tidy line of at most 8 words and 60 characters, or None when nothing usable is left."""
    line = next((ln for ln in text.splitlines() if ln.strip(_EDGE)), "")
    words = line.strip(_EDGE).rstrip(_TRAILING).strip(_EDGE).split()[:MAX_WORDS]
    out = " ".join(words)
    if len(out) > MAX_CHARS:
        cut = out[:MAX_CHARS]
        out = cut.rsplit(" ", 1)[0] if " " in cut else cut
    out = out.strip(_EDGE).rstrip(_TRAILING).strip()
    return out or None
