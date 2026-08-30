from __future__ import annotations

import threading
import time
from collections import defaultdict, deque

from fastapi import Request

from app.core.config import settings
from app.core.exceptions import AppError


class RateLimited(AppError):
    def __init__(self, retry_after: int) -> None:
        super().__init__(
            429,
            "rate_limited",
            "Too many attempts. Please wait a moment and try again.",
        )
        self.headers = {"Retry-After": str(retry_after)}


class SlidingWindowLimiter:
    """In-process sliding-window counter.

    Fine for a single instance. Behind multiple workers/replicas each process
    keeps its own window — swap in a shared Redis backend if that matters.
    """

    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def hit(self, key: str, limit: int, window: float) -> tuple[bool, float]:
        now = time.monotonic()
        cutoff = now - window
        with self._lock:
            q = self._hits[key]
            while q and q[0] <= cutoff:
                q.popleft()
            if len(q) >= limit:
                return False, window - (now - q[0])
            q.append(now)
            return True, 0.0

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


limiter = SlidingWindowLimiter()


def parse_rule(rule: str) -> tuple[int, int]:
    count, _, seconds = rule.partition("/")
    return int(count), int(seconds)


def rate_limit(name: str, rule: str):
    """FastAPI dependency enforcing `rule` ("count/seconds") per client IP."""
    limit, window = parse_rule(rule)

    async def _dep(request: Request) -> None:
        if not settings.RATE_LIMIT_ENABLED:
            return
        client_ip = request.client.host if request.client else "unknown"
        ok, retry_after = limiter.hit(f"{name}:{client_ip}", limit, window)
        if not ok:
            raise RateLimited(retry_after=max(1, int(retry_after) + 1))

    return _dep
