"""Systems under test. Each takes a fresh copy of a task repo and leaves its result there.

* ``patchpilot``               the full pipeline
* ``patchpilot-no-retrieval``  ablation: no migration documentation in prompts
* ``patchpilot-no-repair``     ablation: one patch round, no repair attempts
* ``direct-llm``               baseline: each source file pasted to the same model with
                               "migrate this file", whole-file answer applied as-is.
                               No analysis, no docs, no validation (what a developer
                               gets from a chat window).
* ``bump-pydantic``            Pydantic's official rule-based codemod (no LLM)
"""

from __future__ import annotations

import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

from patchpilot.analyzer.scanner import scan
from patchpilot.llm.patch_generator import request_full_file
from patchpilot.llm.prompts import DIRECT_SYSTEM, direct_prompt
from patchpilot.llm.provider import LLMProvider, LLMQuotaExhausted
from patchpilot.migration.orchestrator import MigrationConfig, Orchestrator
from patchpilot.models import LLMUsage, RunReport
from patchpilot.profiles.base import Profile
from patchpilot.validation.runner import Validator

SYSTEMS = (
    "patchpilot",
    "patchpilot-no-retrieval",
    "patchpilot-no-repair",
    "direct-llm",
    "bump-pydantic",
)
LLM_SYSTEMS = frozenset(s for s in SYSTEMS if s != "bump-pydantic")


@dataclass
class SystemResult:
    repo: Path  # where the migrated code now is
    usage: LLMUsage = field(default_factory=LLMUsage)
    seconds: float = 0.0
    repair_attempts: int = 0
    status: str = ""
    error: str = ""
    report: RunReport | None = None


def run_patchpilot(
    repo: Path,
    profile: Profile,
    provider: LLMProvider,
    validator: Validator,
    *,
    retrieval: bool,
    repairs: int,
) -> SystemResult:
    orch = Orchestrator(
        profile, provider, validator, MigrationConfig(retrieval=retrieval, max_repairs=repairs)
    )
    report = orch.run(repo)
    final = Path(report.workspace) if report.workspace else repo
    return SystemResult(
        repo=final,
        usage=report.usage,
        seconds=report.seconds,
        repair_attempts=report.repair_attempts,
        status=report.status.value,
        error=report.message if report.status.value == "failed" else "",
        report=report,
    )


def run_direct(repo: Path, profile: Profile, provider: LLMProvider) -> SystemResult:
    started = time.monotonic()
    usage = LLMUsage()
    errors = []
    files, _ = scan(repo)
    for f in files:
        if f.is_test:
            continue
        src = f.abspath.read_text(encoding="utf-8")
        if not src.strip():
            continue  # empty __init__.py: nothing to send
        try:
            content, u, err = request_full_file(
                provider, DIRECT_SYSTEM, direct_prompt(profile.title, f.path, src)
            )
        except LLMQuotaExhausted as exc:
            errors.append(str(exc))
            break
        usage.add(u)
        if content is None:
            errors.append(f"{f.path}: {err}")
            continue
        f.abspath.write_text(
            content if content.endswith("\n") else content + "\n", encoding="utf-8"
        )
    return SystemResult(
        repo=repo,
        usage=usage,
        seconds=round(time.monotonic() - started, 3),
        status="done",
        error="; ".join(errors),
    )


def run_bump_pydantic(repo: Path, executable: str = "bump-pydantic") -> SystemResult:
    started = time.monotonic()
    exe = shutil.which(executable)
    if exe is None:
        return SystemResult(repo=repo, status="unavailable", error="bump-pydantic not installed")
    proc = subprocess.run(
        [exe, "."], cwd=repo, capture_output=True, text=True, timeout=300, check=False
    )
    return SystemResult(
        repo=repo,
        seconds=round(time.monotonic() - started, 3),
        status="done" if proc.returncode == 0 else "error",
        error="" if proc.returncode == 0 else proc.stderr[-500:],
    )
