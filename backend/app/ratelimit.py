"""Tiny in-process sliding-window rate limiter (single worker; resets on restart)."""
from __future__ import annotations

import threading
import time
from collections import defaultdict, deque


class RateLimiter:
    def __init__(self, limit: int, window_s: float):
        self.limit, self.window_s = limit, window_s
        self._hits: dict[str, deque] = defaultdict(deque)
        self._lock = threading.Lock()

    def _prune(self, q: deque, now: float) -> None:
        while q and q[0] <= now - self.window_s:
            q.popleft()

    def blocked(self, key: str) -> bool:
        """True if `key` already used up its allowance (does not count a hit)."""
        with self._lock:
            q = self._hits[key]
            self._prune(q, time.monotonic())
            return len(q) >= self.limit

    def hit(self, key: str) -> None:
        with self._lock:
            self._hits[key].append(time.monotonic())

    def allow(self, key: str) -> bool:
        """Count a hit; False when over the limit."""
        with self._lock:
            q = self._hits[key]
            now = time.monotonic()
            self._prune(q, now)
            if len(q) >= self.limit:
                return False
            q.append(now)
            return True

    def clear(self, key: str | None = None) -> None:
        with self._lock:
            if key is None:
                self._hits.clear()
            else:
                self._hits.pop(key, None)


login_failures = RateLimiter(10, 300)
ingest_requests = RateLimiter(600, 60)


def reset_all() -> None:
    login_failures.clear()
    ingest_requests.clear()
