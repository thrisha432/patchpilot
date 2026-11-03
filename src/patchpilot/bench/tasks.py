"""Benchmark tasks on disk.

benchmarks/tasks/<id>/
    task.toml       id, title, difficulty, patterns
    repo/           the v1 project, including its visible tests/
    hidden/         tests only the evaluator runs (catch "passes visible tests, wrong behavior")
    reference/      a hand-written v2 solution (overlay of changed files)
"""

from __future__ import annotations

import shutil
import tempfile
import tomllib
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Task:
    id: str
    title: str
    difficulty: str
    tier: int
    patterns: tuple[str, ...]
    root: Path

    @property
    def repo(self) -> Path:
        return self.root / "repo"

    @property
    def hidden(self) -> Path:
        return self.root / "hidden"

    @property
    def reference(self) -> Path:
        return self.root / "reference"

    def copy_repo(self, with_reference: bool = False) -> Path:
        """A fresh copy of the task repo (optionally with the reference solution applied)."""
        dest = Path(tempfile.mkdtemp(prefix=f"pp-task-{self.id}-")) / "repo"
        shutil.copytree(self.repo, dest)
        if with_reference:
            shutil.copytree(self.reference, dest, dirs_exist_ok=True)
        return dest


def load_tasks(directory: Path, only: list[str] | None = None) -> list[Task]:
    tasks = []
    for toml in sorted(directory.glob("*/task.toml")):
        meta = tomllib.loads(toml.read_text(encoding="utf-8"))
        if only and not any(meta["id"].startswith(o) for o in only):
            continue
        tasks.append(
            Task(
                id=meta["id"],
                title=meta["title"],
                difficulty=meta["difficulty"],
                tier=int(meta.get("tier", 1)),
                patterns=tuple(meta.get("patterns", [])),
                root=toml.parent,
            )
        )
    return tasks
