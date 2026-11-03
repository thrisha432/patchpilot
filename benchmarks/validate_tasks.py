"""Check that every benchmark task is well-formed before trusting any result on it.

For each task:
  1. original code passes visible + hidden tests on Pydantic v1   (the task's code is correct)
  2. original code FAILS on Pydantic v2 (deprecations are errors)  (migration is necessary)
  3. reference solution passes visible + hidden tests on v2        (the task is solvable)
  4. analyzer: findings on the original, residual findings on the reference

Run: .venv/bin/python benchmarks/validate_tasks.py [task-id-prefix ...]
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

from patchpilot.analyzer.analyzer import analyze
from patchpilot.bench.tasks import load_tasks
from patchpilot.profiles import get_profile
from patchpilot.validation.runner import DockerValidator

TASKS = Path(__file__).parent / "tasks"


def main(argv: list[str]) -> int:
    profile = get_profile("pydantic-v2")
    rows = []
    ok_all = True
    for task in load_tasks(TASKS, argv or None):
        v1 = DockerValidator(profile.source_image, (), extra_test_dirs=[task.hidden])
        v2 = DockerValidator(
            profile.target_image, profile.pytest_args, extra_test_dirs=[task.hidden]
        )
        original = task.copy_repo()
        reference = task.copy_repo(with_reference=True)
        try:
            r1 = v1.validate(original)
            r2 = v2.validate(original)
            r3 = v2.validate(reference)
            found = len(analyze(original, profile).actionable())
            residual = len(analyze(reference, profile).actionable())
        finally:
            shutil.rmtree(original.parent, ignore_errors=True)
            shutil.rmtree(reference.parent, ignore_errors=True)
        ok = r1.passed and not r2.passed and r3.passed
        ok_all &= ok
        rows.append(
            {
                "task": task.id,
                "ok": ok,
                "v1_original": f"{r1.n_passed}/{len(r1.tests)}",
                "v2_original_failing": r2.n_failed,
                "v2_reference": f"{r3.n_passed}/{len(r3.tests)}",
                "findings": found,
                "residual_on_reference": residual,
            }
        )
        status = "ok " if ok else "BAD"
        print(
            f"{status} {task.id:32} v1={rows[-1]['v1_original']:6} v2-orig-failing={r2.n_failed:<3} "
            f"v2-ref={rows[-1]['v2_reference']:6} findings={found:<3} residual(ref)={residual}"
        )
        if not ok:
            for label, r in (("v1 original", r1), ("v2 original", r2), ("v2 reference", r3)):
                bad = [t for t in r.tests if t.outcome in ("failed", "error")]
                for t in bad[:3]:
                    print(
                        f"      {label}: {t.nodeid}: {t.message.splitlines()[0][:160] if t.message else ''}"
                    )
                if r.syntax_errors:
                    print(f"      {label}: {r.syntax_errors}")
    out = Path(__file__).parent / "results" / "task_validation.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(rows, indent=2) + "\n", encoding="utf-8")
    print(f"\n{sum(r['ok'] for r in rows)}/{len(rows)} tasks valid -> {out}")
    return 0 if ok_all else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
