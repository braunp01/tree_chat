"""Domain failures, mapped to HTTP error categories by the API layer (design.md, Error Handling)."""

from __future__ import annotations


class DomainError(Exception):
    category: str = "validation"

    def __init__(self, message: str, fields: tuple[str, ...] = ()) -> None:
        super().__init__(message)
        self.message = message
        self.fields = fields


class ValidationError(DomainError):
    category = "validation"

    def __init__(self, field: str, message: str) -> None:
        super().__init__(message, (field,))


class Conflict(DomainError):
    category = "conflict"


class NotFound(DomainError):
    category = "not_found"


class Busy(DomainError):
    category = "busy"
