import threading
import time


class TokenBucket:
    """Thread-safe token bucket rate limiter.

    Starts empty to avoid initial burst. Enforces min spacing of 0.2s
    between releases (max 5 req/sec) to satisfy Alpha Vantage burst policy.
    """

    def __init__(self, capacity: int, refill_rate: float, max_per_sec: float = 5.0):
        self._capacity = capacity
        self._tokens = 0.0  # start empty — no burst at startup
        self._refill_rate = refill_rate  # tokens per second
        self._max_per_sec = max_per_sec
        self._min_spacing = 1.0 / max_per_sec  # min seconds between releases
        self._lock = threading.Lock()
        self._last_refill = time.monotonic()
        self._last_release = 0.0

    def _refill(self):
        now = time.monotonic()
        elapsed = now - self._last_refill
        self._tokens = min(self._capacity, self._tokens + elapsed * self._refill_rate)
        self._last_refill = now

    def acquire(self, tokens: int = 1):
        while True:
            with self._lock:
                self._refill()
                now = time.monotonic()
                spacing_ok = (now - self._last_release) >= self._min_spacing
                if self._tokens >= tokens and spacing_ok:
                    self._tokens -= tokens
                    self._last_release = now
                    return
            time.sleep(0.05)


# Default limiter: 75 req/min average, max 5 req/sec burst
default_limiter = TokenBucket(capacity=10, refill_rate=75 / 60, max_per_sec=5.0)
