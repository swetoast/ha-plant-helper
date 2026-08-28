"""Shared API provider helpers for Plant Helper."""

from __future__ import annotations

from dataclasses import dataclass, field
import asyncio
from datetime import datetime, timedelta
from typing import Any


@dataclass(slots=True)
class ProviderResult:
    """Normalized provider result."""

    found: bool
    provider: str
    data: dict[str, Any] | None = None
    api_checked: bool = False
    api_called: bool = False
    message: str = ""
    calls_made: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)


class RateLimiter:
    """Simple in-memory API limiter for Home Assistant runtime."""

    def __init__(
        self,
        *,
        daily_limit: int | None = None,
        min_interval_seconds: int = 0,
    ) -> None:
        """Initialize limiter."""
        self.daily_limit = daily_limit
        self.min_interval_seconds = min_interval_seconds
        self.calls_today = 0
        self.last_reset = datetime.now().date()
        self.last_call_at: datetime | None = None

    def reset_if_needed(self) -> None:
        """Reset daily counter when date changes."""
        today = datetime.now().date()
        if today != self.last_reset:
            self.last_reset = today
            self.calls_today = 0
            self.last_call_at = None

    def can_call(self) -> bool:
        """Return true if another call is currently allowed."""
        self.reset_if_needed()

        if self.daily_limit is not None and self.calls_today >= self.daily_limit:
            return False

        if self.last_call_at is not None and self.min_interval_seconds > 0:
            next_allowed = self.last_call_at + timedelta(seconds=self.min_interval_seconds)
            if datetime.now() < next_allowed:
                return False

        return True

    def has_daily_capacity(self) -> bool:
        """Return whether the daily allowance has capacity remaining."""
        self.reset_if_needed()
        return self.daily_limit is None or self.calls_today < self.daily_limit

    async def async_wait_for_slot(self) -> bool:
        """Wait for the per-request interval without bypassing the daily cap.

        A provider lookup can legitimately require sequential HTTP requests
        (search then detail/photo). Waiting here prevents the second request in
        one lookup from being rejected by the provider's own throttle.
        """
        self.reset_if_needed()
        if not self.has_daily_capacity():
            return False
        if self.last_call_at is not None and self.min_interval_seconds > 0:
            delay = (
                self.last_call_at + timedelta(seconds=self.min_interval_seconds)
                - datetime.now()
            ).total_seconds()
            if delay > 0:
                await asyncio.sleep(delay)
        self.reset_if_needed()
        return self.has_daily_capacity()

    def mark_call(self) -> None:
        """Record one actual HTTP call."""
        self.reset_if_needed()
        self.calls_today += 1
        self.last_call_at = datetime.now()


def normalize_text(value: Any) -> str:
    """Normalize text for provider matching."""
    text = str(value or "").strip().lower()
    return " ".join(text.replace("-", " ").replace("_", " ").split())


def first_value(value: Any) -> Any:
    """Return first list item or raw value."""
    if isinstance(value, list):
        return value[0] if value else None
    return value


