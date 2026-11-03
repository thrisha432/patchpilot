"""Validate a workspace: syntax check on the host, then pytest in a locked-down container.

The repository under migration is untrusted code (and so is LLM output), so
tests never run on the host. The container gets:

* no network (``--network none``), no Linux capabilities, no privilege escalation;
* a read-only root filesystem, the workspace mounted read-only, and a small
  tmpfs for /tmp; only /out (for the JUnit report) is writable;
* memory, CPU, and process-count limits, and a wall-clock timeout after which
  the container is killed;
* a non-root user and an empty environment: no host variables, so no API keys.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
import time
import uuid
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from patchpilot.analyzer.scanner import scan
from patchpilot.models import TestOutcome, ValidationResult

SANDBOX_REQUIREMENTS = {
    "pydantic-v1": "pydantic==1.10.27 pytest==8.4.2",
    "pydantic-v2": "pydantic==2.14.2 pydantic-settings==2.16.2 pytest==8.4.2",
}


class Validator(Protocol):
    def validate(self, workspace: Path) -> ValidationResult: ...


def syntax_errors(workspace: Path) -> list[str]:
    """compile() only parses; it never executes the code."""
    errors = []
    files, _ = scan(workspace)
    for f in files:
        try:
            compile(f.abspath.read_bytes(), f.path, "exec", dont_inherit=True)
        except SyntaxError as exc:
            errors.append(f"{f.path}:{exc.lineno}: {exc.msg}")
        except ValueError as exc:  # e.g. null bytes
            errors.append(f"{f.path}: {exc}")
    return errors


def parse_junit(path: Path, max_message: int = 4000) -> list[TestOutcome]:
    root = ET.parse(path).getroot()
    cases = []
    for tc in root.iter("testcase"):
        classname, name = tc.get("classname", ""), tc.get("name", "")
        nodeid = f"{classname}::{name}" if classname else name
        outcome, message = "passed", ""
        for child in tc:
            if child.tag in ("failure", "error", "skipped"):
                outcome = {"failure": "failed", "error": "error", "skipped": "skipped"}[child.tag]
                message = f"{child.get('message', '')}\n{child.text or ''}".strip()[:max_message]
                break
        cases.append(TestOutcome(nodeid=nodeid, outcome=outcome, message=message))
    return cases


def docker_available() -> bool:
    if shutil.which("docker") is None:
        return False
    proc = subprocess.run(
        ["docker", "info", "--format", "{{.ServerVersion}}"], capture_output=True, check=False
    )
    return proc.returncode == 0


def image_exists(image: str) -> bool:
    proc = subprocess.run(["docker", "image", "inspect", image], capture_output=True, check=False)
    return proc.returncode == 0


def build_images(dockerfile_dir: Path, tag_prefix: str = "patchpilot-sandbox") -> list[str]:
    built = []
    for variant, reqs in SANDBOX_REQUIREMENTS.items():
        tag = f"{tag_prefix}:{variant}"
        subprocess.run(
            [
                "docker",
                "build",
                "-q",
                "--build-arg",
                f"REQUIREMENTS={reqs}",
                "-t",
                tag,
                str(dockerfile_dir),
            ],
            check=True,
        )
        built.append(tag)
    return built


@dataclass
class DockerValidator:
    image: str
    pytest_args: tuple[str, ...] = ()
    timeout_s: float = 120.0
    memory: str = "768m"
    cpus: str = "1.0"
    extra_test_dirs: list[Path] = field(
        default_factory=list
    )  # mounted read-only, e.g. hidden tests
    # Explicit variables for the container (e.g. PYTHONPATH for a src/ layout).
    # Never copied from the host environment.
    env: dict[str, str] = field(default_factory=dict)

    def command(self, workspace: Path, out_dir: Path, name: str) -> list[str]:
        cmd = [
            "docker", "run", "--rm", "--name", name,
            "--network", "none",
            "--cap-drop", "ALL",
            "--security-opt", "no-new-privileges",
            "--read-only",
            "--tmpfs", "/tmp:rw,nosuid,size=64m",
            "--memory", self.memory, "--memory-swap", self.memory,
            "--cpus", self.cpus,
            "--pids-limit", "256",
            "--user", "10001:10001",
            "-e", "HOME=/tmp",
            "-v", f"{workspace}:/work:ro",
            "-v", f"{out_dir}:/out:rw",
        ]  # fmt: skip
        for key, value in sorted(self.env.items()):
            cmd += ["-e", f"{key}={value}"]
        targets: list[str] = []
        for i, d in enumerate(self.extra_test_dirs):
            cmd += ["-v", f"{d.resolve()}:/extra{i}:ro"]
            targets.append(f"/extra{i}")
        cmd += [
            self.image,
            "python", "-m", "pytest", "-q", "-p", "no:cacheprovider",
            "--rootdir", "/work",
            "--junitxml", "/out/junit.xml", "-o", "junit_family=xunit2",
            *self.pytest_args,
        ]  # fmt: skip
        if targets:
            cmd += ["/work", *targets]
        return cmd

    def validate(self, workspace: Path) -> ValidationResult:
        started = time.monotonic()
        errors = syntax_errors(workspace)
        if errors:
            return ValidationResult(
                stage="syntax",
                passed=False,
                syntax_errors=errors,
                duration_s=time.monotonic() - started,
            )
        out_dir = Path(tempfile.mkdtemp(prefix="patchpilot-out-"))
        out_dir.chmod(0o777)  # the container's non-root user must be able to write the report
        name = f"patchpilot-{uuid.uuid4().hex[:12]}"
        timed_out = False
        try:
            try:
                proc = subprocess.run(
                    self.command(workspace, out_dir, name),
                    capture_output=True,
                    text=True,
                    timeout=self.timeout_s,
                    check=False,
                )
                output, code = (proc.stdout + proc.stderr), proc.returncode
            except subprocess.TimeoutExpired as exc:
                subprocess.run(["docker", "kill", name], capture_output=True, check=False)
                timed_out = True
                output = (
                    (exc.stdout or b"").decode(errors="replace")
                    if isinstance(exc.stdout, bytes)
                    else (exc.stdout or "")
                )
                code = -1
            report = out_dir / "junit.xml"
            tests = parse_junit(report) if report.is_file() else []
        finally:
            shutil.rmtree(out_dir, ignore_errors=True)
        tail = "\n".join(output.strip().splitlines()[-40:])
        # pytest exit codes: 0 all passed, 1 some failed, 5 no tests collected.
        if code == 5:
            return ValidationResult(
                stage="skipped",
                passed=True,
                output_tail=tail,
                duration_s=time.monotonic() - started,
            )
        passed = code == 0 and not timed_out
        if not tests and not passed:
            # pytest crashed before writing a report (e.g. a conftest import error).
            tests = [TestOutcome(nodeid="<pytest>", outcome="error", message=tail[-1500:])]
        return ValidationResult(
            stage="tests",
            passed=passed,
            tests=tests,
            output_tail=tail,
            duration_s=round(time.monotonic() - started, 3),
            timed_out=timed_out,
        )


@dataclass
class ScriptedValidator:
    """Test double: returns scripted results and records the workspace states it saw."""

    results: list[ValidationResult]
    seen: list[dict[str, str]] = field(default_factory=list)

    def validate(self, workspace: Path) -> ValidationResult:
        files, _ = scan(workspace)
        self.seen.append({f.path: f.abspath.read_text(encoding="utf-8") for f in files})
        errors = syntax_errors(workspace)
        if errors:
            return ValidationResult(stage="syntax", passed=False, syntax_errors=errors)
        return self.results.pop(0)
