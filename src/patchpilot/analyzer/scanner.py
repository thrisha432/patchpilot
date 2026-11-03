"""Find the Python files of a repository worth analyzing."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePosixPath

SKIP_DIRS = frozenset(
    {
        ".git",
        ".hg",
        ".venv",
        "venv",
        "env",
        ".tox",
        ".nox",
        "node_modules",
        "__pycache__",
        "build",
        "dist",
        "site-packages",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
    }
)
MAX_FILE_BYTES = 512 * 1024  # generated or vendored files beyond this are skipped


@dataclass(frozen=True)
class SourceFile:
    path: str  # repository-relative POSIX path
    abspath: Path
    is_test: bool


def is_test_path(rel: str) -> bool:
    """pytest's conventions, plus anything under a tests/ or test/ directory.

    Test files are analyzed for context but are never edited: an agent that may
    edit the tests can "pass" by weakening them.
    """
    p = PurePosixPath(rel)
    if any(part in ("tests", "test") for part in p.parts[:-1]):
        return True
    name = p.name
    return name.startswith("test_") or name.endswith("_test.py") or name == "conftest.py"


def scan(root: Path) -> tuple[list[SourceFile], list[str]]:
    """Return (python files sorted by path, skipped entries with reasons)."""
    root = root.resolve()
    files: list[SourceFile] = []
    skipped: list[str] = []
    for path in sorted(root.rglob("*.py")):
        rel_parts = path.relative_to(root).parts
        if any(part in SKIP_DIRS or part.endswith(".egg-info") for part in rel_parts[:-1]):
            continue
        rel = PurePosixPath(*rel_parts).as_posix()
        if path.is_symlink():
            # A symlink could point outside the repository; never follow it.
            skipped.append(f"{rel}: symlink")
            continue
        if path.stat().st_size > MAX_FILE_BYTES:
            skipped.append(f"{rel}: larger than {MAX_FILE_BYTES // 1024} KiB")
            continue
        files.append(SourceFile(rel, path, is_test_path(rel)))
    return files, skipped
