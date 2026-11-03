"""Run systems x tasks x repetitions and record one JSON line per run.

Resumable: rows already in the output file are skipped, so a run interrupted by
the free-tier daily quota continues where it stopped the next day. LLM answers
are cached on disk (benchmarks/.llm-cache), so re-running costs no quota and
replays identical model output.

    .venv/bin/python benchmarks/run_benchmark.py --out benchmarks/results/run1.jsonl
    .venv/bin/python benchmarks/run_benchmark.py --systems patchpilot direct-llm --tasks 01 07
"""

from __future__ import annotations

import argparse
import json
import platform
import shutil
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

from patchpilot.bench.evaluate import score
from patchpilot.bench.systems import (
    LLM_SYSTEMS,
    SYSTEMS,
    run_bump_pydantic,
    run_direct,
    run_patchpilot,
)
from patchpilot.bench.tasks import load_tasks
from patchpilot.llm.factory import DEFAULT_MODEL_SPEC, make_provider
from patchpilot.llm.provider import LLMQuotaExhausted
from patchpilot.profiles import get_profile
from patchpilot.validation.runner import DockerValidator

HERE = Path(__file__).parent


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--systems", nargs="*", default=list(SYSTEMS), choices=SYSTEMS)
    ap.add_argument("--tasks", nargs="*", default=None, help="task id prefixes (default: all)")
    ap.add_argument("--model", default=DEFAULT_MODEL_SPEC)
    ap.add_argument("--reps", type=int, default=1)
    ap.add_argument("--rpm", type=float, default=8.0)
    ap.add_argument("--out", type=Path, default=HERE / "results" / "benchmark.jsonl")
    ap.add_argument("--cache", type=Path, default=HERE / ".llm-cache")
    ap.add_argument("--bump-pydantic", default=str(Path(sys.executable).parent / "bump-pydantic"))
    args = ap.parse_args()

    profile = get_profile("pydantic-v2")
    tasks = load_tasks(HERE / "tasks", args.tasks)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    done = set()
    if args.out.exists():
        for line in args.out.read_text().splitlines():
            row = json.loads(line)
            done.add((row["rep"], row["task"], row["system"]))
    needs_llm = any(s in LLM_SYSTEMS for s in args.systems)
    provider = None
    if needs_llm:
        # Repetitions > 1 must not replay the cache: give each rep its own cache directory.
        provider = {
            rep: make_provider(args.model, args.cache / f"rep{rep}", args.rpm)
            for rep in range(args.reps)
        }
    validator = DockerValidator(profile.target_image, profile.pytest_args)
    meta = {
        "model": args.model,
        "python": platform.python_version(),
        "started": datetime.now(UTC).isoformat(),
    }
    print(f"{len(tasks)} tasks x {len(args.systems)} systems x {args.reps} reps -> {args.out}")

    with args.out.open("a", encoding="utf-8") as out:
        for rep in range(args.reps):
            for task in tasks:
                for system in args.systems:
                    if (rep, task.id, system) in done:
                        continue
                    repo = task.copy_repo()
                    t0 = time.monotonic()
                    try:
                        if system == "bump-pydantic":
                            result = run_bump_pydantic(repo, args.bump_pydantic)
                        elif system.startswith("direct-llm"):
                            assert provider is not None
                            result = run_direct(
                                repo,
                                profile,
                                provider[rep],
                                syntax_guard=system.endswith("guarded"),
                            )
                        else:
                            assert provider is not None
                            result = run_patchpilot(
                                repo,
                                profile,
                                provider[rep],
                                validator,
                                retrieval=system != "patchpilot-no-retrieval",
                                repairs=0 if system == "patchpilot-no-repair" else 2,
                            )
                        if result.report is not None and "quota" in result.report.message.lower():
                            raise LLMQuotaExhausted(result.report.message)
                        if "quota exhausted" in result.error.lower():
                            raise LLMQuotaExhausted(result.error)
                        s = score(task, result.repo, profile)
                    except LLMQuotaExhausted as exc:
                        print(f"\nStopping: {exc}\nRe-run the same command later to resume.")
                        return 3
                    finally:
                        shutil.rmtree(repo.parent, ignore_errors=True)
                    row = {
                        **meta,
                        "rep": rep,
                        "task": task.id,
                        "difficulty": task.difficulty,
                        "system": system,
                        "status": result.status,
                        "error": result.error,
                        "repair_attempts": result.repair_attempts,
                        "llm_calls": result.usage.calls,
                        "prompt_tokens": result.usage.prompt_tokens,
                        "completion_tokens": result.usage.completion_tokens,
                        "llm_seconds": round(result.usage.seconds, 2),
                        "wall_seconds": round(time.monotonic() - t0, 2),
                        **s.as_dict(),
                    }
                    if result.report is not None:
                        Path(result.report.workspace).parent.exists() and shutil.rmtree(
                            Path(result.report.workspace).parent, ignore_errors=True
                        )
                    out.write(json.dumps(row) + "\n")
                    out.flush()
                    mark = "PASS" if s.success else ("REGR" if s.regression else "fail")
                    print(
                        f"rep{rep} {task.id:30} {system:24} {mark}  tests {s.tests_passed}/{s.tests_total}"
                        f"  residual {s.residual_findings}  calls {result.usage.calls}  {row['wall_seconds']}s"
                        + (f"  [{s.failure[:70]}]" if not s.success else "")
                    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
