"""Queue-based logging helpers for pipeline thread → UI streaming."""
from __future__ import annotations

import logging
import queue
import sys
from typing import Any


class QueueHandler(logging.Handler):
    """Emit log records as formatted strings into a queue.Queue."""

    def __init__(self, log_queue: queue.Queue, max_size: int = 10_000) -> None:
        super().__init__()
        self.log_queue = log_queue
        self.max_size = max_size
        self._dropped = 0

    def emit(self, record: logging.LogRecord) -> None:
        try:
            if self.log_queue.qsize() >= self.max_size:
                self._dropped += 1
                return
            self.log_queue.put_nowait(self.format(record))
        except queue.Full:
            self._dropped += 1


class StdoutToQueue:
    """Redirect sys.stdout writes into a queue so print() appears in the UI."""

    def __init__(self, log_queue: queue.Queue, original: Any) -> None:
        self._q = log_queue
        self._orig = original
        self._buf = ""

    def write(self, text: str) -> int:
        self._buf += text
        while "\n" in self._buf:
            line, self._buf = self._buf.split("\n", 1)
            if line:
                try:
                    self._q.put_nowait(line)
                except Exception:
                    pass
        return len(text)

    def flush(self) -> None:
        if self._buf:
            try:
                self._q.put_nowait(self._buf)
            except Exception:
                pass
            self._buf = ""

    def __getattr__(self, name: str) -> Any:
        return getattr(self._orig, name)


def attach_queue_logging(log_queue: queue.Queue) -> tuple[logging.Handler, Any]:
    """Attach QueueHandler to root logger and redirect stdout.

    Returns (handler, original_stdout) for teardown.
    Sets root logger to INFO so pipeline step markers (INFO level) reach the queue.
    """
    handler = QueueHandler(log_queue)
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    )
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(handler)
    for _noisy in ("httpx", "httpcore", "urllib3", "hpack"):
        logging.getLogger(_noisy).setLevel(logging.WARNING)
    orig_stdout = sys.stdout
    sys.stdout = StdoutToQueue(log_queue, orig_stdout)
    return handler, orig_stdout


def detach_queue_logging(handler: logging.Handler, orig_stdout: Any) -> None:
    """Tear down what attach_queue_logging set up."""
    sys.stdout = orig_stdout
    logging.getLogger().removeHandler(handler)
