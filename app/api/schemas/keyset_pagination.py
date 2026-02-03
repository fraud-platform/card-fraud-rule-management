"""Keyset/cursor-based pagination schemas."""

from __future__ import annotations

from enum import Enum
from typing import TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class CursorDirection(str, Enum):
    """Direction for cursor-based pagination."""

    NEXT = "next"
    PREV = "prev"


class KeysetPaginatedResponse[T](BaseModel):
    """Response model for keyset-paginated data."""

    items: list[T]
    next_cursor: str | None = None
    prev_cursor: str | None = None
    has_next: bool
    has_prev: bool
    limit: int
