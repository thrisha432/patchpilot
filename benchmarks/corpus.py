"""Analyzer robustness and precision on large real codebases (parse only, nothing executed).

    .venv/bin/python -I benchmarks/corpus.py run          # analyze every project, write stats
    .venv/bin/python -I benchmarks/corpus.py sample -n 150  # draw findings to label by hand

Projects are pinned in benchmarks/corpus.toml and cloned (shallow) into
benchmarks/.real-cache/corpus. Each project is analyzed in its own subprocess,
so a crash (even a segfault in the parser) is recorded instead of ending the run.
Labels live in benchmarks/results/corpus/labels.jsonl:
    {"id": "<project>:<finding id>", "label": "tp" | "fp", "note": "..."}
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import time
import tomllib
from collections import Counter
from pathlib import Path

HERE = Path(__file__).parent
CORPUS = HERE / ".real-cache" / "corpus"
OUT = HERE / "results" / "corpus"


def projects() -> list[dict]:
    return tomllib.loads((HERE / "corpus.toml").read_text(encoding="utf-8"))["project"]


def fetch(p: dict) -> Path:
    dest = CORPUS / p["name"]
    if not dest.is_dir():
        CORPUS.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            ["git", "clone", "-q", "--depth", "1", "--branch", p["tag"], p["repo"], str(dest)],
            check=True,
        )
    return dest


def analyze_one(root: Path) -> None:
    """Child process: analyze `root`, print the report as JSON."""
    from patchpilot.analyzer.analyzer import analyze
    from patchpilot.profiles import get_profile

    t0 = time.perf_counter()
    report = analyze(root, get_profile("pydantic-v2"))
    print(
        json.dumps({"seconds": time.perf_counter() - t0, "report": report.model_dump(mode="json")})
    )


def run() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    stats, findings = [], []
    for p in projects():
        root = fetch(p)
        proc = subprocess.run(
            [sys.executable, "-I", __file__, "_child", str(root)],
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode != 0:
            stats.append({"project": p["name"], "crashed": True, "exit": proc.returncode,
                          "stderr": proc.stderr[-500:]})  # fmt: skip
            print(f"CRASH {p['name']}: exit {proc.returncode}")
            continue
        data = json.loads(proc.stdout)
        rep = data["report"]
        conf = Counter(f["confidence"] for f in rep["findings"])
        files = rep["files"]
        stats.append({
            "project": p["name"], "tag": p["tag"], "crashed": False,
            "files": len(files), "lines": sum(f["lines"] for f in files),
            "parse_errors": sum(f["parse_error"] for f in files),
            "model_classes": len(rep["model_classes"]),
            "findings": len(rep["findings"]), "by_confidence": dict(conf),
            "by_rule": dict(Counter(f["rule"] for f in rep["findings"]).most_common()),
            "seconds": round(data["seconds"], 2),
        })  # fmt: skip
        for f in rep["findings"]:
            findings.append({"project": p["name"], **f})
        s = stats[-1]
        print(f"{p['name']:10} files={s['files']:<5} lines={s['lines']:<7} parse_errors={s['parse_errors']:<3} "
              f"models={s['model_classes']:<4} findings={s['findings']:<5} {dict(conf)} {s['seconds']}s")  # fmt: skip
    (OUT / "stats.json").write_text(json.dumps(stats, indent=2) + "\n", encoding="utf-8")
    with (OUT / "findings.jsonl").open("w", encoding="utf-8") as fh:
        for f in findings:
            fh.write(json.dumps(f) + "\n")


def sample(n: int, seed: int, only: str | None = None) -> None:
    """Random sample of actionable findings (HIGH/MEDIUM), with code context.

    Each finding's rank is a seeded hash of its id, so the sample is stable: a finding
    keeps its rank when the analyzer adds or drops others.
    """
    rows = [json.loads(ln) for ln in (OUT / "findings.jsonl").read_text().splitlines()]
    actionable = [r for r in rows if r["confidence"] != "low" and only in (None, r["project"])]
    rank = lambda r: hashlib.sha256(f"{seed}:{r['project']}:{r['id']}".encode()).hexdigest()  # noqa: E731
    picked = sorted(
        sorted(actionable, key=rank)[:n], key=lambda r: (r["project"], r["file"], r["line"])
    )
    for r in picked:
        src = (CORPUS / r["project"] / r["file"]).read_text(encoding="utf-8", errors="replace")
        lines = src.splitlines()
        lo, hi = max(0, r["line"] - 4), min(len(lines), r["line"] + 3)
        ctx = "\n".join(
            f"{'>' if i + 1 == r['line'] else ' '}{i + 1:5} {lines[i]}" for i in range(lo, hi)
        )
        print(
            f"### {r['project']}:{r['id']}  [{r['rule']} / {r['confidence']}]\n{r['message']}\n{ctx}\n"
        )


def precision() -> None:
    sys.path.insert(0, str(HERE))
    from stats import wilson

    rows = {
        f"{r['project']}:{r['id']}": r
        for r in map(json.loads, (OUT / "findings.jsonl").read_text().splitlines())
    }
    labels = [
        json.loads(ln) for ln in (OUT / "labels.jsonl").read_text().splitlines() if ln.strip()
    ]
    groups: dict[tuple[str, str], Counter] = {}
    for lab in labels:
        conf = rows[lab["id"]][
            "confidence"
        ]  # KeyError: a label for a finding that no longer exists
        for key in ((lab["sample"], conf), (lab["sample"], "all")):
            groups.setdefault(key, Counter())[lab["label"]] += 1
    print(
        "| Sample | Confidence | True / labelled | Precision | 95% interval |\n|---|---|---|---|---|"
    )
    for (smp, conf), c in sorted(groups.items()):
        n = c["tp"] + c["fp"]
        lo, hi = wilson(c["tp"], n)
        print(
            f"| {smp} | {conf} | {c['tp']}/{n} | {100 * c['tp'] / n:.1f}% | {100 * lo:.1f} to {100 * hi:.1f}% |"
        )


def main() -> None:
    if len(sys.argv) == 3 and sys.argv[1] == "_child":
        analyze_one(Path(sys.argv[2]))
        return
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["run", "sample", "precision"])
    ap.add_argument("-n", type=int, default=150)
    ap.add_argument("--seed", type=int, default=20261102)
    ap.add_argument("--project", help="sample one project only (e.g. the held-out one)")
    args = ap.parse_args()
    {"run": run, "sample": lambda: sample(args.n, args.seed, args.project), "precision": precision}[
        args.cmd
    ]()


if __name__ == "__main__":
    main()
