import threading
import time


class TokenBucket:
    """Thread-safe token bucket rate limiter."""

    def __init__(self, capacity: int, refill_rate: float):
        self._capacity = capacity
        self._tokens = float(capacity)
        self._refill_rate = refill_rate  # tokens per second
        self._lock = threading.Lock()
        self._last_refill = time.monotonic()

    def _refill(self):
        now = time.monotonic()
        elapsed = now - self._last_refill
        self._tokens = min(self._capacity, self._tokens + elapsed * self._refill_rate)
        self._last_refill = now

    def acquire(self, tokens: int = 1):
        while True:
            with self._lock:
                self._refill()
                if self._tokens >= tokens:
                    self._tokens -= tokens
                    return
            time.sleep(0.05)


# Default limiter: 75 requests/minute = 1.25 tokens/second
default_limiter = TokenBucket(capacity=75, refill_rate=75 / 60)
