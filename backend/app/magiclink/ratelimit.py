"""How often one key (an address, an IP) may ask for a link."""

import time
from collections import deque
from collections.abc import Callable
from typing import Protocol


class RateLimiter(Protocol):
    def hit(self, key: str) -> float | None:
        """Count one attempt for `key`: None if allowed, else seconds until one is."""
        ...


class MemoryRateLimiter:
    """A sliding window per key, in this process's memory.

    Enough for one API process, which is how Rakin runs. Several processes would each
    allow `limit`, so a deployment that scales out needs a shared implementation.
    """

    def __init__(
        self,
        *,
        limit: int,
        window_seconds: float,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if limit < 1:
            raise ValueError("limit must be at least 1")
        self.limit = limit
        self.window = window_seconds
        self._clock = clock
        self._hits: dict[str, deque[float]] = {}
        self._swept_at = self._clock()

    def hit(self, key: str) -> float | None:
        now = self._clock()
        cutoff = now - self.window
        # Once a window, drop the keys that stopped asking, so they do not pile up.
        if now - self._swept_at >= self.window:
            for stale in [k for k, hits in self._hits.items() if hits[-1] <= cutoff]:
                del self._hits[stale]
            self._swept_at = now
        hits = self._hits.setdefault(key, deque())
        while hits and hits[0] <= cutoff:
            hits.popleft()
        if len(hits) >= self.limit:
            return hits[0] + self.window - now
        hits.append(now)
        return None
