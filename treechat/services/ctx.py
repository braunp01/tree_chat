"""What every operation needs. Services never call the provider; jobs do (design.md, Layered Responsibilities)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from treechat.domain.model import BranchId, Settings
from treechat.env import Env
from treechat.store.db import Store


def _never_busy(_: BranchId) -> bool:
    return False


@dataclass(frozen=True, slots=True)
class Ctx:
    store: Store
    env: Env
    settings: Settings
    is_busy: Callable[[BranchId], bool] = _never_busy
