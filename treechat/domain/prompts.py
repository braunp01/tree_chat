"""Prompts for the short generated texts (Req 11, 12.1). Pure. Their output is for display and editing only: it
never enters a Context (Req 11.5)."""

from __future__ import annotations

from treechat.domain.model import Role

MAX_MESSAGE_CHARS = 4000
MAX_MESSAGES = 24
INTENT_MAX = 120

_SYSTEM = (
    "You write very short labels and summaries inside a chat app. Reply with the text only: no quotes, "
    "no preamble, no markdown."
)


def _clip(text: str, n: int) -> str:
    return text if len(text) <= n else text[: n - 1] + "…"


def _transcript(messages: list[tuple[Role, str]]) -> str:
    recent = messages[-MAX_MESSAGES:]
    label = {Role.USER: "User", Role.ASSISTANT: "Assistant", Role.NOTE: "Note"}
    return "\n\n".join(f"{label[r]}: {_clip(t, MAX_MESSAGE_CHARS)}" for r, t in recent)


def standing_prompt(intent: str | None, anchor_quote: str, messages: list[tuple[Role, str]]) -> tuple[str, str]:
    """Req 11.2: where a parked Tangent stands, from its own Messages."""
    return _SYSTEM, (
        f"A side conversation about this passage was parked:\n\n<passage>{_clip(anchor_quote, 1000)}</passage>\n"
        + (f"The user's intent: {intent}\n" if intent else "")
        + f"\n<conversation>\n{_transcript(messages)}\n</conversation>\n\n"
        "In one line of at most 120 characters, say where the conversation stands and what is still open."
    )


def conclusion_prompt(intent: str | None, anchor_quote: str, messages: list[tuple[Role, str]]) -> tuple[str, str]:
    """Req 12.1: a draft Conclusion the user will edit."""
    return _SYSTEM, (
        f"A side conversation about this passage is being closed:\n\n<passage>{_clip(anchor_quote, 1000)}</passage>\n"
        + (f"The user's intent: {intent}\n" if intent else "")
        + f"\n<conversation>\n{_transcript(messages)}\n</conversation>\n\n"
        "Write the conclusion to record in the main conversation: what was found or decided, in one to four "
        "sentences and under 1,500 characters. Write it so someone who has not seen the side conversation can use it."
    )


def one_line(text: str, limit: int) -> str:
    """First non-empty line, unquoted, cut to `limit` characters."""
    for line in text.splitlines():
        t = line.strip().strip("\"'“”‘’").strip()
        if t:
            return _clip(t, limit)
    return ""
