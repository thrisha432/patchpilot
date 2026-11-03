"""Score one system's output on one task, the same way for every system.

Integrity rules:
* The original test files are restored before scoring, whatever the system
  did to them (bump-pydantic rewrites tests too; an LLM could weaken them).
* Hidden tests are mounted read-only from outside the repository; no system
  ever sees them.
* Pydantic deprecation warnings are errors, so "still runs through a v1
  compatibility shim" does not count as migrated.
"""

from __future__ import annotations

import difflib
import shutil
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path

from patchpilot.analyzer.analyzer import analyze
from patchpilot.analyzer.scanner import scan
from patchpilot.bench.tasks import Task
from patchpilot.profiles.base import Profile
from patchpilot.validation.runner import DockerValidator


@dataclass
class Score:
    success: bool  # visible + hidden tests pass on the target version
    visible_pass: bool
    regression: bool  # visible tests pass but hidden ones fail: "looks done, isn't"
    tests_passed: int
    tests_total: int
    residual_findings: int  # deprecated patterns the analyzer still finds
    files_changed: int
    collateral_files: int  # changed files the reference solution leaves alone
    lines_changed: int
    reference_lines_changed: int
    failure: str = ""

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def _sources(root: Path) -> dict[str, str]:
    files, _ = scan(root)
    return {
        f.path: f.abspath.read_text(encoding="utf-8", errors="replace")
        for f in files
        if not f.is_test
    }


def _changed(before: dict[str, str], after: dict[str, str]) -> tuple[set[str], int]:
    names = {p for p in before.keys() | after.keys() if before.get(p) != after.get(p)}
    lines = 0
    for p in names:
        diff = difflib.unified_diff(
            before.get(p, "").splitlines(), after.get(p, "").splitlines(), lineterm=""
        )
        lines += sum(1 for ln in diff if ln[:1] in "+-" and not ln.startswith(("+++", "---")))
    return names, lines


def prepare_for_scoring(task: Task, result_repo: Path) -> Path:
    """Copy the result, then put back the task's original test files."""
    dest = Path(tempfile.mkdtemp(prefix=f"pp-eval-{task.id}-")) / "repo"
    shutil.copytree(result_repo, dest, ignore=shutil.ignore_patterns(".git"))
    current, _ = scan(dest)
    for f in current:
        if f.is_test:
            f.abspath.unlink()
    original, _ = scan(task.repo)
    for f in original:
        if f.is_test:
            target = dest / f.path
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(f.abspath, target)
    return dest


def score(task: Task, result_repo: Path, profile: Profile, timeout_s: float = 120.0) -> Score:
    scored = prepare_for_scoring(task, result_repo)
    try:
        visible = DockerValidator(
            profile.target_image, profile.pytest_args, timeout_s=timeout_s
        ).validate(scored)
        combined = DockerValidator(
            profile.target_image,
            profile.pytest_args,
            timeout_s=timeout_s,
            extra_test_dirs=[task.hidden],
        ).validate(scored)
        residual = len(analyze(scored, profile).actionable())
        before = _sources(task.repo)
        after = _sources(scored)
    finally:
        shutil.rmtree(scored.parent, ignore_errors=True)
    reference_dir = task.copy_repo(with_reference=True)
    try:
        ref_changed, ref_lines = _changed(before, _sources(reference_dir))
    finally:
        shutil.rmtree(reference_dir.parent, ignore_errors=True)
    changed, lines = _changed(before, after)
    failing = [t for t in combined.tests if t.outcome in ("failed", "error")]
    failure = ""
    if combined.syntax_errors:
        failure = f"syntax: {combined.syntax_errors[0]}"
    elif failing:
        first = failing[0]
        detail = next(
            (ln for ln in first.message.splitlines() if ln.startswith("E ")), first.message[:120]
        )
        failure = f"{first.nodeid}: {detail.strip()[:200]}"
    elif combined.timed_out:
        failure = "timed out"
    return Score(
        success=combined.passed,
        visible_pass=visible.passed,
        regression=visible.passed and not combined.passed,
        tests_passed=combined.n_passed,
        tests_total=len(combined.tests),
        residual_findings=residual,
        files_changed=len(changed),
        collateral_files=len(changed - ref_changed),
        lines_changed=lines,
        reference_lines_changed=ref_lines,
        failure=failure,
    )
