"""The Docker sandbox really is locked down. Each test runs hostile test code inside it."""

from __future__ import annotations

import os

import pytest

from patchpilot.validation.runner import DockerValidator
from tests.conftest import requires_docker

pytestmark = [pytest.mark.docker, requires_docker]


def run(make_repo, profile, test_src: str, timeout: float = 60.0):
    repo = make_repo({"app/__init__.py": "", "tests/test_probe.py": test_src})
    return DockerValidator(profile.target_image, profile.pytest_args, timeout_s=timeout).validate(
        repo
    )


def test_passing_and_failing_tests_are_reported(make_repo, profile):
    result = run(
        make_repo, profile, "def test_ok():\n    pass\n\ndef test_bad():\n    assert 1 == 2\n"
    )
    assert not result.passed
    assert {t.nodeid.split("::")[-1]: t.outcome for t in result.tests} == {
        "test_ok": "passed",
        "test_bad": "failed",
    }
    assert "assert 1 == 2" in next(t.message for t in result.tests if t.outcome == "failed")


def test_no_network(make_repo, profile):
    probe = (
        "import socket, pytest\n"
        "def test_net():\n"
        "    with pytest.raises(OSError):\n"
        "        socket.create_connection(('1.1.1.1', 53), timeout=3)\n"
    )
    assert run(make_repo, profile, probe).passed


def test_workspace_is_read_only_and_user_is_not_root(make_repo, profile):
    probe = (
        "import os, pytest\n"
        "def test_ro():\n"
        "    assert os.getuid() != 0\n"
        "    with pytest.raises(OSError):\n"
        "        open('/work/app/evil.py', 'w')\n"
        "    with pytest.raises(OSError):\n"
        "        open('/usr/local/lib/evil', 'w')\n"
    )
    assert run(make_repo, profile, probe).passed


def test_host_environment_is_not_visible(make_repo, profile, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "must-not-leak")
    probe = "import os\ndef test_env():\n    assert 'GEMINI_API_KEY' not in os.environ\n"
    assert os.environ["GEMINI_API_KEY"] == "must-not-leak"
    assert run(make_repo, profile, probe).passed


def test_runaway_tests_are_killed_at_the_timeout(make_repo, profile):
    result = run(
        make_repo, profile, "def test_forever():\n    while True:\n        pass\n", timeout=8
    )
    assert result.timed_out and not result.passed and result.duration_s < 30


def test_syntax_errors_are_caught_before_docker(make_repo, profile):
    repo = make_repo(
        {"app/__init__.py": "", "app/m.py": "def f(:\n", "tests/test_x.py": "def test(): pass\n"}
    )
    result = DockerValidator(profile.target_image, profile.pytest_args).validate(repo)
    assert result.stage == "syntax" and result.syntax_errors[0].startswith("app/m.py:1")


def test_pydantic_deprecations_fail_on_target(make_repo, profile):
    repo = make_repo(
        {
            "app/__init__.py": "",
            "app/m.py": "from pydantic import BaseModel\nclass U(BaseModel):\n    a: int\n",
            "tests/test_m.py": "from app.m import U\ndef test():\n    assert U(a=1).dict() == {'a': 1}\n",
        }
    )
    result = DockerValidator(profile.target_image, profile.pytest_args).validate(repo)
    assert not result.passed and "PydanticDeprecatedSince20" in result.tests[0].message
    v1 = DockerValidator(profile.source_image).validate(repo)
    assert v1.passed  # the same code is fine on v1


def test_no_tests_collected(make_repo, profile):
    repo = make_repo({"app/__init__.py": ""})
    assert (
        DockerValidator(profile.target_image, profile.pytest_args).validate(repo).stage == "skipped"
    )
