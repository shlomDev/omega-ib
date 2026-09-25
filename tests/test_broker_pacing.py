import time

from omega_ib.broker.pacing import RateLimiter


def test_rate_limiter_allows_burst_under_limit():
    limiter = RateLimiter(max_calls=5, per_seconds=1.0)
    start = time.monotonic()
    for _ in range(5):
        limiter.acquire()
    assert time.monotonic() - start < 0.5  # no sleeping needed under the limit


def test_rate_limiter_throttles_beyond_limit():
    limiter = RateLimiter(max_calls=2, per_seconds=0.2)
    start = time.monotonic()
    for _ in range(4):
        limiter.acquire()
    elapsed = time.monotonic() - start
    assert elapsed >= 0.15  # the 3rd/4th calls had to wait out the window
