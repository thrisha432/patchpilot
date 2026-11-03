from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from textwrap import dedent

import pytest

from patchpilot.profiles import get_profile
from patchpilot.profiles.base import Profile
from patchpilot.validation.runner import docker_available, image_exists

RepoFactory = Callable[[dict[str, str]], Path]


@pytest.fixture
def make_repo(tmp_path: Path) -> RepoFactory:
    """Write {relative path: source} into a fresh directory and return it."""
    counter = {"n": 0}

    def make(files: dict[str, str]) -> Path:
        counter["n"] += 1
        root = tmp_path / f"repo{counter['n']}"
        for rel, src in files.items():
            path = root / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(dedent(src).lstrip("\n"), encoding="utf-8")
        root.mkdir(exist_ok=True)
        return root

    return make


@pytest.fixture
def profile() -> Profile:
    return get_profile("pydantic-v2")


def _sandbox_ready() -> bool:
    p = get_profile("pydantic-v2")
    return docker_available() and image_exists(p.target_image) and image_exists(p.source_image)


requires_docker = pytest.mark.skipif(
    not _sandbox_ready(), reason="Docker or sandbox images unavailable"
)
