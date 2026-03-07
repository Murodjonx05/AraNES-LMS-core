from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field
from threading import Lock
from typing import Callable


@dataclass(slots=True)
class InMemoryRateLimiter:
    time_fn: Callable[[], float] = time.monotonic
    _lock: Lock = field(default_factory=Lock, init=False, repr=False)
    _buckets: dict[str, deque[float]] = field(default_factory=dict, init=False, repr=False)

    def allow(self, key: str, *, limit: int, window_seconds: int) -> bool:
        now = self.time_fn()
        cutoff = now - float(window_seconds)
        with self._lock:
            bucket = self._buckets.setdefault(key, deque())
            while bucket and bucket[0] <= cutoff:
                bucket.popleft()
            if len(bucket) >= limit:
                return False
            bucket.append(now)
            return True
