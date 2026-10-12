"""What every operation needs. Services never call the provider; jobs do (design.md, Architecture)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from treechat.domain.model import MessageId, Settings
from treechat.env import Env
from treechat.store.db import Store


def _never_busy(_: MessageId) -> bool:
    return False


@dataclass(frozen=True, slots=True)
class Ctx:
    store: Store
    env: Env
    settings: Settings
    # Req 3.7: whether a Reply is being generated for this user Message.
    is_busy: Callable[[MessageId], bool] = _never_busy
