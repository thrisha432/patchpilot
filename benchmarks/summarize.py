"""Summarize benchmark JSONL files into Markdown tables (stdout, or --out file).

.venv/bin/python benchmarks/summarize.py benchmarks/results/*.jsonl --out benchmarks/results/SUMMARY.md
"""

from __future__ import annotations

import argparse
import json
import statistics
import tomllib
from collections import defaultdict
from pathlib import Path

ORDER = [
    "patchpilot",
    "patchpilot-no-retrieval",
    "patchpilot-no-repair",
    "direct-llm",
    "bump-pydantic",
]


def load(paths: list[Path]) -> list[dict]:
    rows = []
    for p in paths:
        rows += [json.loads(line) for line in p.read_text().splitlines() if line.strip()]
    return rows


def pct(n: int, d: int) -> str:
    return f"{n}/{d} ({100 * n / d:.0f}%)" if d else "-"


def summarize(rows: list[dict]) -> str:
    by_system: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_system[r["system"]].append(r)
    systems = [s for s in ORDER if s in by_system] + sorted(set(by_system) - set(ORDER))
    reps = sorted({r["rep"] for r in rows})
    out = [
        "| System | Tasks solved | Solved per repetition | Visible tests pass | Regressions (visible pass, hidden fail) | "
        "Residual deprecated patterns | Collateral files changed | Lines changed (reference) | "
        "Repairs / task | LLM calls / task | Tokens / task | Seconds / task |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for s in systems:
        rs = by_system[s]
        n = len(rs)
        tokens = [r["prompt_tokens"] + r["completion_tokens"] for r in rs]
        per_rep = ", ".join(
            str(sum(r["success"] for r in rs if r["rep"] == rep))
            for rep in sorted({r["rep"] for r in rs})
        )
        out.append(
            f"| {s} | **{pct(sum(r['success'] for r in rs), n)}** | {per_rep} | "
            f"{pct(sum(r['visible_pass'] for r in rs), n)} | "
            f"{sum(r['regression'] for r in rs)} | {sum(r['residual_findings'] for r in rs)} | "
            f"{sum(r['collateral_files'] for r in rs)} | {sum(r['lines_changed'] for r in rs)} "
            f"({sum(r['reference_lines_changed'] for r in rs)}) | "
            f"{statistics.mean(r['repair_attempts'] for r in rs):.2f} | "
            f"{statistics.mean(r['llm_calls'] for r in rs):.1f} | {statistics.mean(tokens):,.0f} | "
            f"{statistics.mean(r['wall_seconds'] for r in rs):.1f} |"
        )
    out.append("")
    out.append(f"Repetitions: {len(reps)}. Counts are over all task x repetition runs.")
    out.append("")

    # Per difficulty
    diffs = ["easy", "medium", "hard"]
    out += ["| System | " + " | ".join(diffs) + " |", "|---|" + "---|" * len(diffs)]
    for s in systems:
        cells = []
        for d in diffs:
            rs = [r for r in by_system[s] if r["difficulty"] == d]
            cells.append(pct(sum(r["success"] for r in rs), len(rs)))
        out.append(f"| {s} | " + " | ".join(cells) + " |")
    out.append("")

    # Per task matrix (rep 0)
    tasks = sorted({r["task"] for r in rows})
    out += ["| Task | " + " | ".join(systems) + " |", "|---|" + "---|" * len(systems)]
    cell: dict[tuple[str, str], list[bool]] = defaultdict(list)
    for r in rows:
        cell[(r["task"], r["system"])].append(r["success"])
    for t in tasks:
        marks = []
        for s in systems:
            v = cell.get((t, s), [])
            marks.append(
                "-"
                if not v
                else ("✅" if all(v) else ("❌" if not any(v) else f"{sum(v)}/{len(v)}"))
            )
        out.append(f"| {t} | " + " | ".join(marks) + " |")
    out.append("")

    # Failure reasons
    out += ["### Failures", ""]
    for s in systems:
        fails = [r for r in by_system[s] if not r["success"]]
        if not fails:
            continue
        out.append(f"**{s}**")
        out.append("")
        for r in fails:
            out.append(f"- `{r['task']}` (rep {r['rep']}): {r['failure'] or r['error'] or '?'}")
        out.append("")
    return "\n".join(out)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="+", type=Path)
    ap.add_argument("--out", type=Path)
    ap.add_argument("--tier", type=int, help="only tasks of this tier")
    args = ap.parse_args()
    rows = load(args.files)
    if args.tier is not None:
        tiers = {
            t.parent.name: tomllib.loads(t.read_text()).get("tier", 1)
            for t in (Path(__file__).parent / "tasks").glob("*/task.toml")
        }
        rows = [r for r in rows if tiers.get(r["task"]) == args.tier]
    text = summarize(rows)
    if args.out:
        args.out.write_text(text + "\n", encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
