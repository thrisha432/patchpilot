from __future__ import annotations

import pytest

from patchpilot.migration.workspace import Workspace, WorkspaceError


@pytest.fixture
def repo(make_repo):
    return make_repo(
        {
            "app/m.py": "a = 1\n",
            "tests/test_m.py": "def test(): pass\n",
            ".venv/bin/python": "binary",
            "README.md": "hi\n",
        }
    )


def test_copy_excludes_venv_and_commits_baseline(repo):
    ws = Workspace.create(repo)
    try:
        assert (ws.root / "app/m.py").is_file() and not (ws.root / ".venv").exists()
        assert ws.baseline == ws.head() and ws.changed_files() == []
    finally:
        ws.cleanup()


def test_write_diff_restore(repo):
    ws = Workspace.create(repo)
    try:
        ws.write("app/m.py", "a = 2\n")
        c1 = ws.commit("round 0")
        (ws.root / "app/new.py").write_text("n = 1\n")
        ws.write("app/m.py", "a = 3\n")
        ws.commit("round 1")
        assert ws.changed_files() == ["app/m.py", "app/new.py"]
        ws.restore(c1)
        assert ws.read("app/m.py") == "a = 2\n" and not (ws.root / "app/new.py").exists()
        assert "-a = 1\n+a = 2" in ws.diff()
        ws.restore(ws.baseline)
        assert ws.changed_files() == []
        assert (repo / "app/m.py").read_text() == "a = 1\n"  # the original was never touched
    finally:
        ws.cleanup()


def test_refuses_tests_and_escaping_paths(repo):
    ws = Workspace.create(repo)
    try:
        with pytest.raises(WorkspaceError, match="test file"):
            ws.write("tests/test_m.py", "def test(): assert True\n")
        for bad in ("../outside.py", "/etc/passwd", "app/../../x.py"):
            with pytest.raises(WorkspaceError, match="escapes"):
                ws.resolve(bad)
    finally:
        ws.cleanup()


def test_symlinks_are_not_followed(make_repo, tmp_path):
    secret = tmp_path / "secret.txt"
    secret.write_text("s3cret")
    repo = make_repo({"app/m.py": "a = 1\n"})
    (repo / "app/link.py").symlink_to(secret)
    ws = Workspace.create(repo)
    try:
        with pytest.raises(WorkspaceError, match="symlink"):
            ws.read("app/link.py")
    finally:
        ws.cleanup()


def test_apply_to_original_checks_for_concurrent_changes(repo):
    ws = Workspace.create(repo)
    try:
        ws.write("app/m.py", "a = 2\n")
        ws.commit("change")
        (repo / "app/m.py").write_text("a = 99\n")  # someone edited the original meanwhile
        with pytest.raises(WorkspaceError, match="changed in the original"):
            ws.apply_to_original()
        assert (repo / "app/m.py").read_text() == "a = 99\n"
        (repo / "app/m.py").write_text("a = 1\n")
        assert ws.apply_to_original() == ["app/m.py"]
        assert (repo / "app/m.py").read_text() == "a = 2\n"
    finally:
        ws.cleanup()


def test_user_git_config_is_ignored(repo, monkeypatch, tmp_path):
    hooks = tmp_path / "hooks"
    hooks.mkdir()
    (hooks / "pre-commit").write_text("#!/bin/sh\nexit 1\n")
    (hooks / "pre-commit").chmod(0o755)
    cfg = tmp_path / "gitconfig"
    cfg.write_text(f"[core]\n\thooksPath = {hooks}\n[commit]\n\tgpgsign = true\n")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(cfg))
    ws = Workspace.create(repo)  # would fail if the hook or signing applied
    try:
        ws.write("app/m.py", "a = 5\n")
        ws.commit("ok")
    finally:
        ws.cleanup()
