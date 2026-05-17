"""FullPipeline orchestrator — owns pipeline_runs row + step iteration."""
from __future__ import annotations

import datetime as dt
import json
import logging
import traceback
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable

from models import PipelineRun
from pipeline.base import (
    PipelineError,
    PipelineStep,
    StepContext,
    StepResult,
)


@contextmanager
def _open_session(factory):
    s = factory()
    if hasattr(s, "__enter__"):
        with s as session:
            yield session
    else:
        try:
            yield s
        finally:
            s.close()


def _serialize_result(r: StepResult) -> dict:
    return {
        "step_name": r.step_name,
        "status": r.status,
        "summary": r.summary,
        "payload": r.payload,
        "error": r.error,
    }


def _step_to_markdown(r: StepResult) -> str:
    lines = [
        f"# Step: {r.step_name}",
        "",
        f"**Status:** {r.status}",
    ]
    if r.error:
        lines.append("")
        lines.append("## Error")
        lines.append("")
        lines.append("```")
        lines.append(r.error)
        lines.append("```")
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    lines.append("```json")
    lines.append(json.dumps(r.summary, indent=2, default=str))
    lines.append("```")
    if r.payload:
        lines.append("")
        lines.append("## Payload")
        lines.append("")
        lines.append("```json")
        lines.append(json.dumps(r.payload, indent=2, default=str))
        lines.append("```")
    return "\n".join(lines)


class FullPipeline:
    def __init__(
        self,
        steps: list[PipelineStep],
        cfg: dict[str, Any],
        session_factory: Callable[[], Any],
        report_root: Path,
        logger: logging.Logger | None = None,
        resume_from: str | None = None,
        run_id: int | None = None,
        only: str | None = None,
    ):
        self.steps = steps
        self.cfg = cfg
        self.session_factory = session_factory
        self.report_root = Path(report_root)
        self.logger = logger or logging.getLogger(__name__)
        self.resume_from = resume_from
        self.only = only
        if resume_from and run_id is None:
            raise ValueError("run_id is required when resume_from is specified")
        self.run_id = run_id

    def run(self) -> int:
        run_id = self._init_run()
        report_dir = self.report_root / str(run_id)
        report_dir.mkdir(parents=True, exist_ok=True)

        ctx = StepContext(
            cfg=self.cfg,
            run_id=run_id,
            report_dir=report_dir,
            logger=self.logger,
            session_factory=self.session_factory,
            prior_results=self._load_prior_results(report_dir),
        )

        steps_to_run = self._select_steps()
        for step in steps_to_run:
            self.logger.info("=== running step: %s ===", step.name)
            try:
                result = step.run(ctx)
            except Exception as e:
                tb = traceback.format_exc()
                result = StepResult(
                    step_name=step.name,
                    status="failed",
                    summary={},
                    error=f"{type(e).__name__}: {e}\n{tb}",
                )
            self._write_step_report(report_dir, result)
            ctx.prior_results[step.name] = result

            if result.status == "failed":
                self._mark_run(run_id, status="failed")
                self._write_summary(report_dir, ctx.prior_results, status="failed")
                raise PipelineError(
                    f"step {step.name!r} failed: {result.error}"
                )

        self._mark_run(run_id, status="success")
        self._write_summary(report_dir, ctx.prior_results, status="success")
        return run_id

    # --- run lifecycle helpers ----------------------------------------------

    def _init_run(self) -> int:
        if self.run_id is None:
            with _open_session(self.session_factory) as s:
                run = PipelineRun(status="running")
                s.add(run)
                s.commit()
                return run.id
        with _open_session(self.session_factory) as s:
            run = s.query(PipelineRun).filter_by(id=self.run_id).one()
            if run.status == "success":
                raise PipelineError(
                    f"pipeline_run {self.run_id} is already success; cannot resume"
                )
            run.status = "running"
            s.commit()
            return run.id

    def _mark_run(self, run_id: int, status: str) -> None:
        with _open_session(self.session_factory) as s:
            run = s.query(PipelineRun).filter_by(id=run_id).one()
            run.status = status
            run.finished_at = dt.datetime.utcnow()
            s.commit()

    def _select_steps(self) -> list[PipelineStep]:
        if self.only:
            return [s for s in self.steps if s.name == self.only]
        if self.resume_from:
            names = [s.name for s in self.steps]
            if self.resume_from not in names:
                raise ValueError(
                    f"resume_from={self.resume_from!r} not in steps {names}"
                )
            idx = names.index(self.resume_from)
            return self.steps[idx:]
        return list(self.steps)

    def _load_prior_results(self, report_dir: Path) -> dict[str, StepResult]:
        out: dict[str, StepResult] = {}
        for f in report_dir.glob("*.json"):
            if f.name == "summary.json":
                continue
            try:
                body = json.loads(f.read_text())
            except Exception:
                continue
            if "step_name" in body:
                out[body["step_name"]] = StepResult(
                    step_name=body["step_name"],
                    status=body["status"],
                    summary=body.get("summary", {}),
                    payload=body.get("payload", {}),
                    error=body.get("error"),
                )
        return out

    def _write_step_report(self, report_dir: Path, result: StepResult) -> None:
        (report_dir / f"{result.step_name}.json").write_text(
            json.dumps(_serialize_result(result), indent=2, default=str)
        )
        (report_dir / f"{result.step_name}.md").write_text(
            _step_to_markdown(result)
        )

    def _write_summary(
        self,
        report_dir: Path,
        results: dict[str, StepResult],
        status: str,
    ) -> None:
        steps_block = {
            name: {
                "status": r.status,
                "summary": r.summary,
                "error": r.error,
            }
            for name, r in results.items()
        }
        body = {
            "status": status,
            "finished_at": dt.datetime.utcnow().isoformat(),
            "steps": steps_block,
        }
        (report_dir / "summary.json").write_text(
            json.dumps(body, indent=2, default=str)
        )
        md = ["# Pipeline summary", "", f"**Overall:** {status}", ""]
        for name, r in results.items():
            md.append(f"- **{name}** — {r.status}")
            if r.error:
                md.append(f"    - error: {r.error.splitlines()[0]}")
        (report_dir / "summary.md").write_text("\n".join(md))
