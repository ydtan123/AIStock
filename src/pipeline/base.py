"""Pipeline base abstractions: StepResult, StepContext, PipelineStep ABC."""
from __future__ import annotations

import logging
import threading
from abc import ABC, abstractmethod
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable


class PipelineError(Exception):
    """Raised by the orchestrator when a step fails terminally."""


class PipelineStopped(PipelineError):
    """Raised by the orchestrator when stop_event is set mid-run."""


@dataclass
class StepResult:
    step_name: str
    status: str  # "success" | "skipped" | "failed"
    summary: dict[str, Any]
    payload: dict[str, Any] = field(default_factory=dict)
    error: str | None = None


@dataclass
class StepContext:
    cfg: dict[str, Any]
    run_id: int
    report_dir: Path
    logger: logging.Logger
    session_factory: Callable[[], Any]
    prior_results: dict[str, StepResult] = field(default_factory=dict)
    stop_event: threading.Event | None = None

    def is_stopped(self) -> bool:
        return self.stop_event is not None and self.stop_event.is_set()


class RegisteredBackend(ABC):
    """Mixin: enforces that subclasses define a non-empty `name` class attribute."""

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        # Only validate concrete subclasses, not intermediate ABCs.
        # __abstractmethods__ is set by ABCMeta after __init_subclass__
        # fires, so scan class dict for @abstractmethod markers directly.
        if any(
            hasattr(v, "__isabstractmethod__")
            for v in vars(cls).values()
        ):
            return
        if not getattr(cls, "name", None):
            raise TypeError(
                f"{cls.__name__} must define a non-empty `name` class attribute"
            )


class PipelineStep(ABC):
    name: str = ""

    def __init__(self):
        if not self.name:
            raise TypeError(
                f"{type(self).__name__} must define a non-empty `name` class attribute"
            )

    @abstractmethod
    def run(self, ctx: StepContext) -> StepResult: ...

    def step_config(self, ctx: StepContext) -> dict[str, Any]:
        return ctx.cfg.get(self.name, {})


@contextmanager
def open_session(ctx: StepContext):
    """Wrap session_factory; tolerate both context-manager and plain factories."""
    s = ctx.session_factory()
    if hasattr(s, "__enter__"):
        with s as session:
            yield session
    else:
        try:
            yield s
        finally:
            s.close()
