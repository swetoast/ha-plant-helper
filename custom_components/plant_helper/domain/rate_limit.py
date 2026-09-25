from __future__ import annotations

from typing import Any

# A provider that has run out of its window and reports no reset gets this
# cooldown before we probe it again.
DEFAULT_COOLDOWN_SECONDS = 60.0


class RateLimitGate:
    """Self-regulates calls to a provider that publishes RateLimit-* headers.

    Trefle allows 60 requests per minute and returns RateLimit-Limit,
    RateLimit-Remaining and RateLimit-Reset (a unix timestamp) on every response,
    with a 429 once the window is spent. This gate reads those so we stop calling
    before hitting the limit rather than absorbing 429s: allow() is False while the
    provider is known-exhausted, until the reported reset time; observe() updates
    that window from each response's status and headers.

    The clock is injected (now, a unix timestamp) so the logic stays pure.
    """

    def __init__(self, cooldown_seconds: float = DEFAULT_COOLDOWN_SECONDS) -> None:
        self._cooldown = cooldown_seconds
        self._blocked_until = 0.0

    def allow(self, now: float) -> bool:
        """True when a request may be made now."""
        return now >= self._blocked_until

    def observe(self, status: int, remaining: Any, reset: Any, now: float) -> None:
        """Update the window from one response's status and RateLimit headers."""
        reset_ts = _to_float(reset)
        remaining_n = _to_int(remaining)
        exhausted = status == 429 or (remaining_n is not None and remaining_n <= 0)
        if exhausted:
            self._blocked_until = (
                reset_ts if reset_ts is not None and reset_ts > now else now + self._cooldown
            )
        elif remaining_n is not None and remaining_n > 0:
            # The provider confirmed headroom; clear any earlier block.
            self._blocked_until = 0.0


def _to_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _to_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
