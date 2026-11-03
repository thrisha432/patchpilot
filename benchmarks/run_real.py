"""Evaluate systems on real open-source migrations (benchmarks/real/*.toml).

    .venv/bin/python benchmarks/run_real.py --validate-only
    .venv/bin/python benchmarks/run_real.py --model claude-code:claude-haiku-5-5 --reps 3

Per task:
  required tests = tests that must pass after migration:
      target_tests = "migration": the maintainers' post-migration tests that pass on
                                  the maintainers' own v2 code (never shown to systems);
      target_tests = "base":      the base tests that passed on Pydantic v1.
  validity: the base code fails at least one required test on v2 (migration needed).
Systems see only the repository at the base commit, including its base tests.
Score: all required tests pass on v2 (deprecations raised by the package are errors).
"""

from __future__ import annotations

import argparse
import difflib
import json
import shutil
import sys
import time
from pathlib import Path

from patchpilot.analyzer.analyzer import analyze
from patchpilot.analyzer.scanner import scan
from patchpilot.bench.real import (
    RealTask,
    build_images,
    checkout_copy,
    cleanup,
    load_real_tasks,
    with_target_tests,
)
from patchpilot.bench.systems import run_bump_pydantic, run_direct, run_patchpilot
from patchpilot.llm.factory import make_provider
from patchpilot.llm.provider import LLMQuotaExhausted
from patchpilot.profiles import get_profile
from patchpilot.validation.runner import image_exists

HERE = Path(__file__).parent
CACHE = HERE / ".real-cache"


def passing(result) -> set[str]:
    return {t.nodeid for t in result.tests if t.outcome == "passed"}


def sources(root: Path) -> dict[str, str]:
    files, _ = scan(root)
    return {
        f.path: f.abspath.read_text(encoding="utf-8", errors="replace")
        for f in files
        if not f.is_test
    }


def changed_lines(before: dict[str, str], after: dict[str, str]) -> tuple[set[str], int]:
    names = {p for p in before.keys() | after.keys() if before.get(p) != after.get(p)}
    n = 0
    for p in names:
        diff = difflib.unified_diff(
            before.get(p, "").splitlines(), after.get(p, "").splitlines(), lineterm=""
        )
        n += sum(1 for ln in diff if ln[:1] in "+-" and not ln.startswith(("+++", "---")))
    return names, n


def required_tests(task: RealTask) -> tuple[set[str], dict]:
    base = checkout_copy(task, CACHE)
    ref = checkout_copy(task, CACHE, with_reference=True)
    try:
        if task.target_tests == "migration":
            scored_ref = with_target_tests(task, CACHE, ref)
            reference = task.validator().validate(scored_ref)
            cleanup(scored_ref)
            required = passing(reference)
        else:
            reference = None
            required = passing(task.validator(target=False).validate(base))
        scored_base = with_target_tests(task, CACHE, base)
        before = task.validator().validate(scored_base)
        cleanup(scored_base)
        _, ref_lines = changed_lines(sources(base), sources(ref))
        info = {
            "required": len(required),
            "base_passing_on_v2": len(passing(before) & required),
            "reference_passes_all": reference is not None and required <= passing(reference),
            "reference_lines_changed": ref_lines,
            "findings": len(analyze(base, get_profile("pydantic-v2")).actionable()),
        }
    finally:
        cleanup(base)
        cleanup(ref)
    return required, info


def score(task: RealTask, result_repo: Path, required: set[str]) -> dict:
    scored = with_target_tests(task, CACHE, result_repo)
    try:
        v = task.validator().validate(scored)
        residual = len(analyze(scored, get_profile("pydantic-v2")).actionable())
    finally:
        cleanup(scored)
    base = checkout_copy(task, CACHE)
    ref = checkout_copy(task, CACHE, with_reference=True)
    try:
        before = sources(base)
        changed, lines = changed_lines(before, sources(result_repo))
        ref_changed, _ = changed_lines(before, sources(ref))
    finally:
        cleanup(base)
        cleanup(ref)
    got = passing(v) & required
    missing = sorted(required - got)
    first = ""
    for t in v.tests:
        if t.nodeid in missing:
            first = f"{t.nodeid}: " + next(
                (ln.strip() for ln in t.message.splitlines() if ln.startswith("E ")),
                t.message[:150],
            )
            break
    if v.syntax_errors:
        first = f"syntax: {v.syntax_errors[0]}"
    return {
        "success": not missing,
        "required_passed": len(got),
        "required_total": len(required),
        "residual_findings": residual,
        "files_changed": len(changed),
        "files_outside_reference": len(changed - ref_changed)
        if task.target_tests == "migration"
        else None,
        "lines_changed": lines,
        "failure": first[:300],
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tasks", nargs="*")
    ap.add_argument("--systems", nargs="*", default=["patchpilot", "direct-llm", "bump-pydantic"])
    ap.add_argument("--model", default="claude-code:claude-haiku-5-5")
    ap.add_argument("--reps", type=int, default=3)
    ap.add_argument("--out", type=Path, default=HERE / "results" / "real" / "real.jsonl")
    ap.add_argument("--validate-only", action="store_true")
    ap.add_argument("--cache", type=Path, default=HERE / ".llm-cache-real")
    args = ap.parse_args()

    tasks = load_real_tasks(HERE / "real", args.tasks)
    validity = {}
    for task in tasks:
        if not (image_exists(task.v1_image) and image_exists(task.v2_image)):
            print(f"building images for {task.id} ...")
            build_images(task)
        required, info = required_tests(task)
        validity[task.id] = (required, info)
        ok = info["required"] > 0 and info["base_passing_on_v2"] < info["required"]
        print(f"{'ok ' if ok else 'BAD'} {task.id:24} required={info['required']:<4} base-on-v2={info['base_passing_on_v2']:<4} "
              f"maintainers-pass-all={info['reference_passes_all']} findings={info['findings']}")  # fmt: skip
    args.out.parent.mkdir(parents=True, exist_ok=True)
    (args.out.parent / "validity.json").write_text(
        json.dumps({k: v[1] for k, v in validity.items()}, indent=2) + "\n", encoding="utf-8"
    )
    if args.validate_only:
        return 0

    done = set()
    if args.out.exists():
        done = {
            (r["rep"], r["task"], r["system"])
            for r in map(json.loads, args.out.read_text().splitlines())
        }
    profile = get_profile("pydantic-v2")
    providers = {
        rep: make_provider(args.model, args.cache / f"rep{rep}") for rep in range(args.reps)
    }
    bump = str(Path(sys.executable).parent / "bump-pydantic")
    with args.out.open("a", encoding="utf-8") as out:
        for rep in range(args.reps):
            for task in tasks:
                required, info = validity[task.id]
                for system in args.systems:
                    if system == "bump-pydantic" and rep > 0:
                        continue  # deterministic
                    if (rep, task.id, system) in done:
                        continue
                    repo = checkout_copy(task, CACHE)
                    t0 = time.monotonic()
                    try:
                        if system == "patchpilot":
                            result = run_patchpilot(
                                repo,
                                profile,
                                providers[rep],
                                task.validator(),
                                retrieval=True,
                                repairs=2,
                            )
                        elif system.startswith("direct-llm"):
                            result = run_direct(
                                repo,
                                profile,
                                providers[rep],
                                syntax_guard=system.endswith("guarded"),
                            )
                        else:
                            result = run_bump_pydantic(repo, bump)
                        if result.report is not None and "quota" in result.report.message.lower():
                            raise LLMQuotaExhausted(result.report.message)
                        s = score(task, result.repo, required)
                    except LLMQuotaExhausted as exc:
                        print(f"Stopping: {exc}. Re-run to resume.")
                        return 3
                    finally:
                        cleanup(repo)
                    if result.report is not None and result.report.workspace:
                        shutil.rmtree(Path(result.report.workspace).parent, ignore_errors=True)
                    row = {
                        "rep": rep, "task": task.id, "system": system, "model": args.model,
                        "status": result.status, "repair_attempts": result.repair_attempts,
                        "llm_calls": result.usage.calls, "prompt_tokens": result.usage.prompt_tokens,
                        "completion_tokens": result.usage.completion_tokens,
                        "reference_lines_changed": info["reference_lines_changed"],
                        "wall_seconds": round(time.monotonic() - t0, 1), **s,
                    }  # fmt: skip
                    out.write(json.dumps(row) + "\n")
                    out.flush()
                    print(f"rep{rep} {task.id:24} {system:14} {'PASS' if s['success'] else 'fail'} "
                          f"{s['required_passed']}/{s['required_total']} residual={s['residual_findings']} "
                          f"calls={result.usage.calls} {row['wall_seconds']}s {s['failure'][:90]}", flush=True)  # fmt: skip
    return 0


if __name__ == "__main__":
    sys.exit(main())
