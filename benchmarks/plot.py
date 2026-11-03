"""Charts for the README and benchmark report, drawn from the JSONL results only.

    .venv/bin/python benchmarks/plot.py benchmarks/results/v0.2/*.jsonl

Writes docs/images/{solve_rate,ablation,task_matrix}.png. Only rows for the model
given by --model-id (plus bump-pydantic, which uses no model) are plotted.
"""

from __future__ import annotations

import argparse
import json
import tomllib
from collections import defaultdict
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import LinearSegmentedColormap

HERE = Path(__file__).resolve().parent
OUT = HERE.parent / "docs" / "images"
SURFACE = "#fcfcfb"
TEXT = "#0b0b0b"
TEXT_2 = "#52514e"
GRID = "#e4e3df"
ACCENT = "#2a78d6"  # categorical slot 1: the system the chart is about
NEUTRAL = "#a3a29c"  # everything else recedes
LABELS = {
    "patchpilot": "PatchPilot",
    "patchpilot-no-retrieval": "PatchPilot without docs",
    "patchpilot-no-repair": "PatchPilot without repair",
    "direct-llm": "Direct prompt (same model)",
    "bump-pydantic": "bump-pydantic (rule-based)",
}
TIER_TITLES = {
    1: "Tier 1: single pattern (23 tasks)",
    2: "Tier 2: realistic (9 tasks)",
    3: "Tier 3: held-out (8 tasks)",
}


def load(paths: list[Path], model_id: str) -> list[dict]:
    tiers = {
        t.parent.name: tomllib.loads(t.read_text()).get("tier", 1)
        for t in (HERE / "tasks").glob("*/task.toml")
    }
    rows = []
    for p in paths:
        for line in p.read_text().splitlines():
            if not line.strip():
                continue
            r = json.loads(line)
            if r["system"] != "bump-pydantic" and model_id not in r["model"]:
                continue
            r["tier"] = tiers.get(r["task"], 1)
            rows.append(r)
    return rows


def style(ax) -> None:
    ax.set_facecolor(SURFACE)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(GRID)
    ax.tick_params(colors=TEXT_2, length=0)
    ax.xaxis.grid(True, color=GRID, zorder=0)
    ax.set_xlim(0, 135)
    ax.set_xticks([0, 50, 100], ["0%", "50%", "100%"])


def bars(
    ax,
    rows: list[dict],
    systems: list[str],
    highlight: str = "patchpilot",
    show_labels: bool = True,
) -> None:
    for i, s in enumerate(reversed(systems)):
        rs = [r for r in rows if r["system"] == s]
        if not rs:
            continue
        solved, total = sum(r["success"] for r in rs), len(rs)
        rate = 100 * solved / total
        ax.barh(i, rate, height=0.58, color=ACCENT if s == highlight else NEUTRAL, zorder=2)
        ax.text(
            rate + 3, i, f"{rate:.0f}%  ({solved}/{total})", va="center", color=TEXT, fontsize=9.5
        )
    ax.set_yticks(
        range(len(systems)),
        [LABELS[s] for s in reversed(systems)] if show_labels else [""] * len(systems),
        color=TEXT,
        fontsize=10,
    )


def solve_rate(rows: list[dict], model: str, out: Path) -> None:
    systems = ["patchpilot", "direct-llm", "bump-pydantic"]
    fig, axes = plt.subplots(1, 3, figsize=(14, 3.0), dpi=200)
    fig.patch.set_facecolor(SURFACE)
    for k, (ax, tier) in enumerate(zip(axes, (1, 2, 3), strict=True)):
        style(ax)
        bars(ax, [r for r in rows if r["tier"] == tier], systems, show_labels=k == 0)
        ax.set_title(TIER_TITLES[tier], loc="left", color=TEXT, fontsize=10.5)
    fig.suptitle(
        f"Runs solved: visible + hidden tests pass on Pydantic v2  ·  {model}, 3 repetitions per task",
        x=0.01, ha="left", color=TEXT, fontsize=12,
    )  # fmt: skip
    fig.tight_layout()
    fig.savefig(out, facecolor=SURFACE)
    plt.close(fig)


def ablation(rows: list[dict], model: str, out: Path) -> None:
    systems = ["patchpilot", "patchpilot-no-retrieval", "patchpilot-no-repair", "direct-llm"]
    hard = [r for r in rows if r["tier"] in (2, 3)]
    fig, ax = plt.subplots(figsize=(8.5, 2.9), dpi=200)
    fig.patch.set_facecolor(SURFACE)
    style(ax)
    bars(ax, hard, systems)
    title = f"What each part adds: tiers 2 + 3 (17 tasks × 3 repetitions), {model}"  # noqa: RUF001
    ax.set_title(title, loc="left", color=TEXT, fontsize=11)
    fig.tight_layout()
    fig.savefig(out, facecolor=SURFACE)
    plt.close(fig)


def task_matrix(rows: list[dict], out: Path) -> None:
    cells: dict[tuple[str, str], list[bool]] = defaultdict(list)
    for r in rows:
        cells[(r["task"], r["system"])].append(r["success"])
    tasks = sorted({r["task"] for r in rows})
    systems = [s for s in LABELS if any((t, s) in cells for t in tasks)]
    data = [
        [
            sum(cells[(t, s)]) / len(cells[(t, s)]) if cells.get((t, s)) else float("nan")
            for s in systems
        ]
        for t in tasks
    ]
    cmap = LinearSegmentedColormap.from_list("blue", ["#eef3fb", "#9cc0ee", ACCENT, "#0d4a96"])
    fig, ax = plt.subplots(figsize=(1.5 * len(systems) + 3.0, 0.26 * len(tasks) + 1.4), dpi=200)
    fig.patch.set_facecolor(SURFACE)
    ax.imshow(data, cmap=cmap, vmin=0, vmax=1, aspect="auto")
    for y, t in enumerate(tasks):
        for x, s in enumerate(systems):
            v = cells.get((t, s))
            if v:
                ax.text(x, y, f"{sum(v)}/{len(v)}", ha="center", va="center", fontsize=7.5,
                        color="white" if sum(v) / len(v) > 0.6 else TEXT)  # fmt: skip
    ax.set_xticks(
        range(len(systems)),
        [LABELS[s].replace(" (", "\n(").replace(" without", "\nwithout") for s in systems],
        fontsize=8.5,
        color=TEXT,
    )
    ax.set_yticks(range(len(tasks)), tasks, fontsize=8, color=TEXT)
    ax.xaxis.tick_top()
    ax.tick_params(length=0)
    for side in ax.spines.values():
        side.set_visible(False)
    ax.set_xticks([x - 0.5 for x in range(1, len(systems))], minor=True)
    ax.set_yticks([y - 0.5 for y in range(1, len(tasks))], minor=True)
    ax.grid(which="minor", color=SURFACE, linewidth=2)
    ax.tick_params(which="minor", length=0)
    for boundary in (22.5, 31.5):  # tier boundaries (tasks 01-23 | 24-32 | 33-40)
        ax.axhline(boundary, color=TEXT_2, linewidth=1.2)
    fig.tight_layout()
    fig.savefig(out, facecolor=SURFACE)
    plt.close(fig)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="+", type=Path)
    ap.add_argument("--model-id", default="claude-haiku-5-5")
    ap.add_argument("--model", default="Claude Haiku 5.5")
    args = ap.parse_args()
    rows = load(args.files, args.model_id)
    OUT.mkdir(parents=True, exist_ok=True)
    solve_rate(rows, args.model, OUT / "solve_rate.png")
    ablation(rows, args.model, OUT / "ablation.png")
    task_matrix(rows, OUT / "task_matrix.png")
    print(f"wrote {sorted(p.name for p in OUT.glob('*.png'))}")


if __name__ == "__main__":
    main()
