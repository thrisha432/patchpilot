"""Uncertainty for the benchmark: Wilson intervals and paired tests (stdlib only).

    .venv/bin/python benchmarks/stats.py benchmarks/results/v0.2/*.jsonl

* Wilson 95% interval for each solve rate (better than the normal approximation at small n).
* Paired comparison of PatchPilot vs the direct prompt on the same (task, repetition):
  - run level: exact McNemar test on discordant runs (optimistic: runs of one task are
    correlated, so they are not independent samples);
  - task level: exact sign test on tasks where one system solved more runs than the other
    (conservative: one vote per task).
"""

from __future__ import annotations

import argparse
import json
import math
import tomllib
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).parent


def wilson(k: int, n: int, z: float = 1.959964) -> tuple[float, float]:
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return max(0.0, centre - half), min(1.0, centre + half)


def binom_two_sided(k: int, n: int) -> float:
    """Exact two-sided binomial test p-value for k successes of n at p = 0.5."""
    if n == 0:
        return 1.0
    tail = sum(math.comb(n, i) for i in range(0, min(k, n - k) + 1)) / 2**n
    return min(1.0, 2 * tail)


def load(paths: list[Path]) -> list[dict]:
    tiers = {
        t.parent.name: tomllib.loads(t.read_text()).get("tier", 1)
        for t in (HERE / "tasks").glob("*/task.toml")
    }
    rows = []
    for p in paths:
        for line in p.read_text().splitlines():
            if line.strip():
                r = json.loads(line)
                r["tier"] = tiers.get(r["task"], 0)
                rows.append(r)
    return rows


def compare(rows: list[dict], a: str, b: str) -> dict[str, object]:
    by: dict[tuple[str, int], dict[str, bool]] = defaultdict(dict)
    for r in rows:
        if r["system"] in (a, b):
            by[(r["task"], r["rep"])][r["system"]] = r["success"]
    pairs = [v for v in by.values() if a in v and b in v]
    a_only = sum(v[a] and not v[b] for v in pairs)
    b_only = sum(v[b] and not v[a] for v in pairs)
    per_task: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for (task, _), v in by.items():
        if a in v and b in v:
            per_task[task][0] += v[a]
            per_task[task][1] += v[b]
    better = sum(x > y for x, y in per_task.values())
    worse = sum(x < y for x, y in per_task.values())
    return {
        "pairs": len(pairs),
        "a_only": a_only,
        "b_only": b_only,
        "p_runs": binom_two_sided(min(a_only, b_only), a_only + b_only),
        "tasks_better": better,
        "tasks_worse": worse,
        "p_tasks": binom_two_sided(min(better, worse), better + worse),
    }


def fmt_p(p: float) -> str:
    return f"{p:.4f}" if p >= 0.0001 else "< 0.0001"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="+", type=Path)
    ap.add_argument("--model-id", default="claude-haiku-5-5")
    args = ap.parse_args()
    rows = [
        r
        for r in load(args.files)
        if r["system"] == "bump-pydantic" or args.model_id in r.get("model", "")
    ]
    groups = {"Tier 1": [1], "Tier 2": [2], "Tier 3 (held-out)": [3], "Tiers 2 + 3": [2, 3]}
    print("| Group | System | Solved | 95% interval |\n|---|---|---|---|")
    for name, tiers in groups.items():
        for s in ("patchpilot", "direct-llm"):
            rs = [r for r in rows if r["tier"] in tiers and r["system"] == s]
            k, n = sum(r["success"] for r in rs), len(rs)
            if n == 0:
                continue
            lo, hi = wilson(k, n)
            print(
                f"| {name} | {s} | {k}/{n} ({100 * k / n:.0f}%) | {100 * lo:.0f} to {100 * hi:.0f}% |"
            )
    print(
        "\n| Group | Runs only PatchPilot solved | Runs only direct solved | p (runs, McNemar) | Tasks PatchPilot better / worse | p (tasks, sign test) |"
    )
    print("|---|---|---|---|---|---|")
    for name, tiers in groups.items():
        c = compare([r for r in rows if r["tier"] in tiers], "patchpilot", "direct-llm")
        if not c["pairs"]:
            continue
        print(
            f"| {name} | {c['a_only']} | {c['b_only']} | {fmt_p(c['p_runs'])} | "
            f"{c['tasks_better']} / {c['tasks_worse']} | {fmt_p(c['p_tasks'])} |"
        )


if __name__ == "__main__":
    main()
