"""HTTP API: submit migration jobs and inspect their progress, report, and diff.

Jobs run one at a time on a background worker (free-tier LLM quotas and the
Docker sandbox both favour serial execution). The API never writes to the
original repository: results stay in the job's workspace and are returned as
a report and a diff for a human to review. Repository paths must live under
an allowed root (``PATCHPILOT_ALLOWED_ROOTS``, colon-separated), so the API
cannot be pointed at arbitrary directories on the machine.
"""

from __future__ import annotations

import os
import threading
import uuid
from collections import OrderedDict
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, HTTPException
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

from patchpilot import __version__
from patchpilot.analyzer.analyzer import analyze
from patchpilot.llm.factory import DEFAULT_MODEL_SPEC, make_provider
from patchpilot.llm.provider import LLMProvider
from patchpilot.migration.orchestrator import MigrationConfig, Orchestrator
from patchpilot.models import AnalysisReport, RunReport, StepRecord
from patchpilot.profiles import get_profile
from patchpilot.profiles.base import Profile
from patchpilot.reporting.report import to_markdown
from patchpilot.validation.runner import DockerValidator, Validator

MAX_JOBS = 100

ProviderFactory = Callable[[str], LLMProvider]
ValidatorFactory = Callable[[Profile], Validator]


class MigrationRequest(BaseModel):
    repo_path: str
    profile: str = "pydantic-v2"
    model: str = DEFAULT_MODEL_SPEC
    max_repairs: int = Field(default=2, ge=0, le=5)
    retrieval: bool = True


class AnalyzeRequest(BaseModel):
    repo_path: str
    profile: str = "pydantic-v2"


class JobView(BaseModel):
    id: str
    state: Literal["queued", "running", "done", "error"]
    created_at: datetime
    repo_path: str
    steps: list[StepRecord] = Field(default_factory=list)
    status: str | None = None  # RunStatus once done
    error: str | None = None
    summary: dict[str, Any] | None = None


@dataclass
class _Job:
    id: str
    request: MigrationRequest
    created_at: datetime
    state: Literal["queued", "running", "done", "error"] = "queued"
    steps: list[StepRecord] = field(default_factory=list)
    report: RunReport | None = None
    error: str | None = None

    def view(self) -> JobView:
        summary = None
        if self.report is not None:
            r = self.report
            summary = {
                "changed_files": r.changed_files,
                "findings": len(r.analysis.actionable()),
                "residual_findings": len(r.residual_findings),
                "repair_attempts": r.repair_attempts,
                "llm_calls": r.usage.calls,
                "seconds": r.seconds,
            }
        return JobView(
            id=self.id,
            state=self.state,
            created_at=self.created_at,
            repo_path=self.request.repo_path,
            steps=list(self.steps),
            status=self.report.status.value if self.report else None,
            error=self.error,
            summary=summary,
        )


def allowed_roots() -> list[Path]:
    raw = os.environ.get("PATCHPILOT_ALLOWED_ROOTS")
    roots = raw.split(":") if raw else [str(Path.cwd())]
    return [Path(r).resolve() for r in roots if r]


def check_repo_path(repo_path: str, roots: list[Path]) -> Path:
    path = Path(repo_path).resolve()  # resolves symlinks and ".." before the check
    if not any(path.is_relative_to(root) for root in roots):
        raise HTTPException(
            403, "repo_path is outside the allowed roots (PATCHPILOT_ALLOWED_ROOTS)"
        )
    if not path.is_dir():
        raise HTTPException(404, "repo_path is not a directory")
    return path


def create_app(
    provider_factory: ProviderFactory | None = None,
    validator_factory: ValidatorFactory | None = None,
    roots: list[Path] | None = None,
) -> FastAPI:
    make_prov: ProviderFactory = provider_factory or (lambda spec: make_provider(spec))
    make_val: ValidatorFactory = validator_factory or (
        lambda p: DockerValidator(p.target_image, p.pytest_args)
    )
    root_list = roots if roots is not None else allowed_roots()
    jobs: OrderedDict[str, _Job] = OrderedDict()
    lock = threading.Lock()
    executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="patchpilot-job")

    app = FastAPI(title="PatchPilot", version=__version__)

    def run_job(job: _Job) -> None:
        job.state = "running"
        try:
            profile = get_profile(job.request.profile)
            orch = Orchestrator(
                profile,
                make_prov(job.request.model),
                make_val(profile),
                MigrationConfig(
                    retrieval=job.request.retrieval, max_repairs=job.request.max_repairs
                ),
            )
            job.report = orch.run(Path(job.request.repo_path))
            job.steps = job.report.steps
            job.state = "done"
        except Exception as exc:  # surfaced to the client; the worker must survive
            job.error = f"{type(exc).__name__}: {exc}"
            job.state = "error"

    def get_job(job_id: str) -> _Job:
        with lock:
            job = jobs.get(job_id)
        if job is None:
            raise HTTPException(404, "no such job")
        return job

    @app.get("/v1/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    @app.post("/v1/analyze")
    def analyze_repo(req: AnalyzeRequest) -> AnalysisReport:
        path = check_repo_path(req.repo_path, root_list)
        try:
            profile = get_profile(req.profile)
        except KeyError as exc:
            raise HTTPException(400, str(exc)) from exc
        return analyze(path, profile)

    @app.post("/v1/migrations", status_code=202)
    def submit(req: MigrationRequest) -> JobView:
        path = check_repo_path(req.repo_path, root_list)
        try:
            get_profile(req.profile)
        except KeyError as exc:
            raise HTTPException(400, str(exc)) from exc
        job = _Job(
            id=uuid.uuid4().hex[:12],
            request=req.model_copy(update={"repo_path": str(path)}),
            created_at=datetime.now(UTC),
        )
        with lock:
            # Bound memory: drop the oldest finished jobs.
            while len(jobs) >= MAX_JOBS:
                oldest = next((k for k, j in jobs.items() if j.state in ("done", "error")), None)
                if oldest is None:
                    raise HTTPException(429, "too many unfinished jobs")
                del jobs[oldest]
            jobs[job.id] = job
        executor.submit(run_job, job)
        return job.view()

    @app.get("/v1/migrations")
    def list_jobs() -> list[JobView]:
        with lock:
            return [j.view() for j in reversed(jobs.values())]

    @app.get("/v1/migrations/{job_id}")
    def job_status(job_id: str) -> JobView:
        return get_job(job_id).view()

    def finished(job_id: str) -> RunReport:
        job = get_job(job_id)
        if job.report is None:
            raise HTTPException(409, f"job is {job.state}")
        return job.report

    @app.get("/v1/migrations/{job_id}/report")
    def job_report(job_id: str) -> RunReport:
        return finished(job_id)

    @app.get("/v1/migrations/{job_id}/report.md", response_class=PlainTextResponse)
    def job_report_md(job_id: str) -> str:
        return to_markdown(finished(job_id))

    @app.get("/v1/migrations/{job_id}/diff", response_class=PlainTextResponse)
    def job_diff(job_id: str) -> PlainTextResponse:
        return PlainTextResponse(finished(job_id).diff, media_type="text/x-diff")

    app.state.executor = executor
    return app


app = create_app()
