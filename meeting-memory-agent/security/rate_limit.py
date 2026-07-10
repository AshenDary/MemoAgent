"""Simple in-memory rate limiting for the FastAPI app."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from threading import Lock
from time import monotonic
from typing import Deque, Dict, Tuple


@dataclass
class RateLimitResult:
    """Result of a rate-limit check."""

    allowed: bool
    retry_after_seconds: int = 0


class RateLimiter:
    """Fixed-window per-client rate limiter.

    This is intentionally simple and in-memory for practice and local use.
    It is not distributed and resets when the process restarts.
    """

    def __init__(self, max_requests: int = 60, window_seconds: int = 60) -> None:
        if max_requests < 1:
            raise ValueError("max_requests must be at least 1")
        if window_seconds < 1:
            raise ValueError("window_seconds must be at least 1")

        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._lock = Lock()
        self._requests: Dict[Tuple[str, str], Deque[float]] = {}

    def allow(self, *, client_id: str, scope: str) -> RateLimitResult:
        """Record a request and return whether it is allowed."""
        now = monotonic()
        key = (client_id, scope)

        with self._lock:
            timestamps = self._requests.setdefault(key, deque())
            self._prune(timestamps=timestamps, now=now)

            if len(timestamps) >= self.max_requests:
                retry_after = self._retry_after_seconds(timestamps=timestamps, now=now)
                return RateLimitResult(allowed=False, retry_after_seconds=retry_after)

            timestamps.append(now)
            return RateLimitResult(allowed=True)

    def reset(self) -> None:
        """Clear all tracked request windows."""
        with self._lock:
            self._requests.clear()

    def _prune(self, *, timestamps: Deque[float], now: float) -> None:
        cutoff = now - self.window_seconds
        while timestamps and timestamps[0] <= cutoff:
            timestamps.popleft()

    def _retry_after_seconds(self, *, timestamps: Deque[float], now: float) -> int:
        if not timestamps:
            return self.window_seconds

        oldest = timestamps[0]
        remaining = self.window_seconds - int(now - oldest)
        return max(1, remaining)


def build_rate_limiter() -> RateLimiter:
    """Build the default request limiter from environment-friendly defaults."""
    return RateLimiter(max_requests=60, window_seconds=60)
