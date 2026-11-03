"""Real-repository tasks: open-source projects whose maintainers migrated to Pydantic v2.

Each task pins two commits from the project's own history:

* ``base``: the last commit before the migration (the input);
* ``migration``: the maintainers' migration (the reference solution: its
  non-test files overlaid on the base).

Scoring uses the project's **own test suite at the base commit**, run on
Pydantic v2. Pydantic deprecation warnings are errors **only when raised from
the package's own modules** (``-W error::...:<package>``): real test suites
often call deprecated APIs themselves, and the system under test may not edit
tests. Nothing here is written by PatchPilot's author except the task file.

The repositories are cloned at run time (not vendored) and never imported on
the host: their code only ever runs inside the sandbox.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
import tomllib
from dataclasses import dataclass
from pathlib import Path

from patchpilot.analyzer.scanner import is_test_path
from patchpilot.validation.runner import DockerValidator

SANDBOX_DIR = Path(__file__).resolve().parents[3] / "sandbox"


@dataclass(frozen=True)
class RealTask:
    id: str
    title: str
    repo: str
    license: str
    base: str
    migration: str
    package: str
    pythonpath: str
    v1_requirements: str
    v2_requirements: str
    # "migration": maintainers' post-migration tests; "base": the base tests that pass on v1.
    target_tests: str = "migration"
    env: tuple[
        tuple[str, str], ...
    ] = ()  # extra container variables, e.g. mock credentials from tox.ini

    @property
    def name(self) -> str:
        return self.id.removeprefix("real-")

    @property
    def v1_image(self) -> str:
        return f"patchpilot-real:{self.name}-v1"

    @property
    def v2_image(self) -> str:
        return f"patchpilot-real:{self.name}-v2"

    def pytest_args(self) -> tuple[str, ...]:
        """Deprecations are errors when raised from the package's own modules.

        Not `-W ...:<module>`: pytest treats that module name literally and anchors it, so
        it would match `pkg` but not `pkg.sub`. An ini-style filter is a regex.
        `package` may list several top-level packages (`a|b`).
        """
        pattern = f"({self.package})(\\..*)?"
        return (
            "--continue-on-collection-errors",  # one broken test module must not hide the rest
            "-o",
            f"filterwarnings=error::pydantic.warnings.PydanticDeprecatedSince20:{pattern}",
        )

    def validator(self, target: bool = True, timeout_s: float = 300.0) -> DockerValidator:
        return DockerValidator(
            self.v2_image if target else self.v1_image,
            self.pytest_args() if target else (),
            timeout_s=timeout_s,
            env={"PYTHONPATH": self.pythonpath, **dict(self.env)},
        )


def load_real_tasks(directory: Path, only: list[str] | None = None) -> list[RealTask]:
    tasks = []
    for path in sorted(directory.glob("*.toml")):
        meta = tomllib.loads(path.read_text(encoding="utf-8"))
        if only and not any(o in meta["id"] for o in only):
            continue
        fields = {k: meta[k] for k in RealTask.__dataclass_fields__ if k in meta}
        fields["env"] = tuple(sorted(meta.get("env", {}).items()))
        tasks.append(RealTask(**fields))
    return tasks


def _git(cwd: Path, *args: str) -> str:
    proc = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True)
    return proc.stdout


def fetch(task: RealTask, cache: Path) -> Path:
    """Clone once into the cache; return the clone (checked out at nothing in particular)."""
    clone = cache / task.name
    if not (clone / ".git").is_dir():
        cache.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "clone", "-q", task.repo, str(clone)], check=True)
    return clone


def checkout_copy(task: RealTask, cache: Path, with_reference: bool = False) -> Path:
    """A fresh copy of the base commit (optionally with the maintainers' non-test changes)."""
    clone = fetch(task, cache)
    dest = Path(tempfile.mkdtemp(prefix=f"pp-real-{task.name}-")) / "repo"
    dest.mkdir()
    archive = subprocess.run(
        ["git", "archive", task.base], cwd=clone, capture_output=True, check=True
    )
    subprocess.run(["tar", "-x", "-C", str(dest)], input=archive.stdout, check=True)
    if with_reference:
        changed = _git(clone, "diff", "--name-status", task.base, task.migration).splitlines()
        for line in changed:
            status, *paths = line.split("\t")
            rel = paths[-1]
            if not rel.endswith(".py") or is_test_path(rel):
                continue
            target = dest / rel
            if status.startswith("D"):
                target.unlink(missing_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(
                subprocess.run(
                    ["git", "show", f"{task.migration}:{rel}"],
                    cwd=clone,
                    capture_output=True,
                    check=True,
                ).stdout
            )
    return dest


def with_target_tests(task: RealTask, cache: Path, repo: Path) -> Path:
    """A copy of `repo` whose test files are the scoring suite (systems never see this one)."""
    dest = Path(tempfile.mkdtemp(prefix=f"pp-real-score-{task.name}-")) / "repo"
    shutil.copytree(repo, dest, ignore=shutil.ignore_patterns(".git"))
    for path in list(dest.rglob("*.py")):
        if is_test_path(path.relative_to(dest).as_posix()):
            path.unlink()
    commit = task.migration if task.target_tests == "migration" else task.base
    clone = fetch(task, cache)
    for rel in _git(clone, "ls-tree", "-r", "--name-only", commit).splitlines():
        if rel.endswith(".py") and is_test_path(rel):
            target = dest / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(
                subprocess.run(
                    ["git", "show", f"{commit}:{rel}"], cwd=clone, capture_output=True, check=True
                ).stdout
            )
    return dest


def build_images(task: RealTask) -> None:
    for tag, reqs in ((task.v1_image, task.v1_requirements), (task.v2_image, task.v2_requirements)):
        subprocess.run(
            [
                "docker",
                "build",
                "-q",
                "--build-arg",
                f"REQUIREMENTS={reqs}",
                "-t",
                tag,
                str(SANDBOX_DIR),
            ],
            check=True,
            capture_output=True,
        )


def cleanup(path: Path) -> None:
    shutil.rmtree(path.parent, ignore_errors=True)
