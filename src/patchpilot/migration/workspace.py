"""An isolated, git-tracked copy of the repository being migrated.

The original repository is never modified during a run. Every patch round is
a commit in the workspace, so "restore the last known-good version" is a
checkout, and the final diff is ``git diff baseline``. Writing results back to
the original is a separate, explicit step that first verifies the original
has not changed since the run started.
"""

from __future__ import annotations

import hashlib
import shutil
import subprocess
import tempfile
from pathlib import Path, PurePosixPath

from patchpilot.analyzer.scanner import SKIP_DIRS, is_test_path

_GIT_ENV = {
    "GIT_AUTHOR_NAME": "PatchPilot",
    "GIT_AUTHOR_EMAIL": "patchpilot@localhost",
    "GIT_COMMITTER_NAME": "PatchPilot",
    "GIT_COMMITTER_EMAIL": "patchpilot@localhost",
    # Ignore the user's global/system git config (signing, hooks, templates).
    "GIT_CONFIG_GLOBAL": "/dev/null",
    "GIT_CONFIG_NOSYSTEM": "1",
}


class WorkspaceError(Exception):
    pass


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _ignore(directory: str, names: list[str]) -> set[str]:
    return {n for n in names if n in SKIP_DIRS or n.endswith(".egg-info")}


class Workspace:
    def __init__(self, original: Path, root: Path, hashes: dict[str, str]) -> None:
        self.original = original
        self.root = root
        self._original_hashes = hashes
        self.baseline = ""

    @classmethod
    def create(cls, original: Path, parent: Path | None = None) -> Workspace:
        original = original.resolve()
        if not original.is_dir():
            raise WorkspaceError(f"not a directory: {original}")
        root = Path(tempfile.mkdtemp(prefix="patchpilot-", dir=parent)) / "repo"
        # symlinks=True copies links as links; files outside the repo are never pulled in.
        shutil.copytree(original, root, ignore=_ignore, symlinks=True)
        hashes = {
            p.relative_to(root).as_posix(): _sha256(p)
            for p in root.rglob("*")
            if p.is_file() and not p.is_symlink()
        }
        ws = cls(original, root, hashes)
        ws._git("init", "-q", "-b", "patchpilot")
        ws._git("add", "-A")
        ws._git(
            "commit", "-q", "--allow-empty", "--no-verify", "-m", "baseline: original repository"
        )
        ws.baseline = ws.head()
        return ws

    # -- git -----------------------------------------------------------------------

    def _git(self, *args: str) -> str:
        proc = subprocess.run(
            ["git", "-c", "core.hooksPath=/dev/null", "-c", "commit.gpgsign=false", *args],
            cwd=self.root,
            capture_output=True,
            text=True,
            env={**_minimal_env(), **_GIT_ENV},
            check=False,
        )
        if proc.returncode != 0:
            raise WorkspaceError(f"git {args[0]} failed: {proc.stderr.strip()[:300]}")
        return proc.stdout

    def head(self) -> str:
        return self._git("rev-parse", "HEAD").strip()

    def commit(self, message: str) -> str:
        self._git("add", "-A")
        self._git("commit", "-q", "--allow-empty", "--no-verify", "-m", message)
        return self.head()

    def restore(self, commit: str) -> None:
        """Make the working tree exactly match a previous commit."""
        self._git("checkout", "-q", commit, "--", ".")
        self._git("clean", "-q", "-fd")
        # Files added after `commit` are not removed by checkout: remove them via diff.
        added = self._git("diff", "--name-only", "--diff-filter=A", commit, "HEAD").split()
        for rel in added:
            (self.root / rel).unlink(missing_ok=True)
        self.commit(f"restore {commit[:10]}")

    def diff(self, against: str | None = None) -> str:
        return self._git("diff", against or self.baseline, "--", ".")

    def changed_files(self, against: str | None = None) -> list[str]:
        out = self._git("diff", "--name-only", against or self.baseline, "--", ".")
        return sorted(line for line in out.splitlines() if line)

    # -- files ---------------------------------------------------------------------

    def resolve(self, rel: str) -> Path:
        """Repository-relative path -> absolute path, refusing anything outside the workspace."""
        p = PurePosixPath(rel)
        if p.is_absolute() or ".." in p.parts:
            raise WorkspaceError(f"path escapes the workspace: {rel}")
        path = self.root / p
        if path.is_symlink() or not path.resolve().is_relative_to(self.root.resolve()):
            raise WorkspaceError(f"refusing symlink or outside path: {rel}")
        return path

    def read(self, rel: str) -> str:
        return self.resolve(rel).read_text(encoding="utf-8")

    def write(self, rel: str, content: str) -> None:
        if is_test_path(rel):
            # Structural guarantee: an agent that may edit tests can "pass" by weakening them.
            raise WorkspaceError(f"refusing to modify a test file: {rel}")
        self.resolve(rel).write_text(content, encoding="utf-8")

    # -- applying back to the original -----------------------------------------------

    def apply_to_original(self) -> list[str]:
        """Copy changed files back, after checking the original was not modified meanwhile."""
        changed = self.changed_files()
        for rel in changed:
            target = self.original / rel
            expected = self._original_hashes.get(rel)
            current = _sha256(target) if target.is_file() else None
            if current != expected:
                raise WorkspaceError(
                    f"{rel} changed in the original repository since the run started; "
                    "not overwriting it. Re-run the migration."
                )
        for rel in changed:
            src = self.resolve(rel)
            dst = self.original / rel
            if src.exists():
                tmp = dst.with_name(dst.name + ".patchpilot-tmp")
                shutil.copyfile(src, tmp)
                tmp.replace(dst)  # atomic per file
            else:
                dst.unlink(missing_ok=True)
        return changed

    def cleanup(self) -> None:
        shutil.rmtree(self.root.parent, ignore_errors=True)


def _minimal_env() -> dict[str, str]:
    import os

    return {
        k: v for k, v in os.environ.items() if k in ("PATH", "HOME", "LANG", "TMPDIR", "SYSTEMROOT")
    }
