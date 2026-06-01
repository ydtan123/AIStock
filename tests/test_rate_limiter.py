"""Tests for TokenBucket rate limiter (src/fetcher/rate_limiter.py)."""
import threading
import time

import pytest

from fetcher.rate_limiter import TokenBucket, default_limiter


class TestTokenBucket:
    def test_initial_tokens_are_zero(self):
        tb = TokenBucket(capacity=10, refill_rate=10.0, max_per_sec=100)
        assert tb._tokens == 0.0

    def test_acquire_after_refill_succeeds(self):
        tb = TokenBucket(capacity=10, refill_rate=100.0, max_per_sec=100)
        time.sleep(0.2)
        start = time.monotonic()
        tb.acquire()
        elapsed = time.monotonic() - start
        assert elapsed < 0.5

    def test_consecutive_acquires_respect_max_per_sec(self):
        tb = TokenBucket(capacity=100, refill_rate=100.0, max_per_sec=5.0)
        start = time.monotonic()
        for _ in range(5):
            tb.acquire()
        elapsed = time.monotonic() - start
        assert elapsed >= 0.7

    def test_acquire_blocks_when_empty(self):
        tb = TokenBucket(capacity=1, refill_rate=2.0, max_per_sec=100)
        tb.acquire()
        start = time.monotonic()
        t = threading.Thread(target=tb.acquire)
        t.start()
        t.join(timeout=3.0)
        elapsed = time.monotonic() - start
        assert elapsed >= 0.3
        assert not t.is_alive()

    def test_thread_safety(self):
        tb = TokenBucket(capacity=100, refill_rate=500.0, max_per_sec=100)
        errors = []

        def worker():
            try:
                for _ in range(5):
                    tb.acquire()
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert len(errors) == 0


def test_default_limiter_exists():
    assert default_limiter is not None
    assert isinstance(default_limiter, TokenBucket)
