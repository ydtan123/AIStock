"""Pipeline base abstractions: StepResult, StepContext, PipelineStep ABC."""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable


class PipelineError(Exception):
    """Raised by the orchestrator when a step fails terminally."""


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
