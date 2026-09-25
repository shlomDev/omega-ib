"""Rate limiter for IB API calls.

IB's guidance is to stay well under ~50 messages/sec to avoid the Gateway
throttling or dropping the client. `RateLimiter.acquire()` blocks just long
enough to keep the caller under `max_calls` per `per_seconds`, using a sliding
window of call timestamps.
"""

from __future__ import annotations

import threading
import time


class RateLimiter:
    def __init__(self, max_calls: int = 40, per_seconds: float = 1.0) -> None:
        self.max_calls = max_calls
        self.per_seconds = per_seconds
        self._calls: list[float] = []
        self._lock = threading.Lock()

    def acquire(self) -> None:
        with self._lock:
            now = time.monotonic()
            self._calls = [t for t in self._calls if now - t < self.per_seconds]
            if len(self._calls) >= self.max_calls:
                sleep_for = self.per_seconds - (now - self._calls[0])
                if sleep_for > 0:
                    time.sleep(sleep_for)
                now = time.monotonic()
                self._calls = [t for t in self._calls if now - t < self.per_seconds]
            self._calls.append(now)
