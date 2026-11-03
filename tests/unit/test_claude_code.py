"""ClaudeCodeProvider with a fake CLI runner (no real calls)."""

from __future__ import annotations

import json
import subprocess

import pytest

from patchpilot.llm.claude_code import ClaudeCodeProvider
from patchpilot.llm.provider import LLMError, LLMQuotaExhausted, LLMTimeout

OK = {
    "type": "result",
    "subtype": "success",
    "is_error": False,
    "result": '{"a": 1}',
    "structured_output": {"a": 1},
    "total_cost_usd": 0.0012,
    "usage": {
        "input_tokens": 5,
        "cache_creation_input_tokens": 100,
        "cache_read_input_tokens": 20,
        "output_tokens": 40,
    },
}


class FakeRunner:
    def __init__(self, *outputs):
        self.outputs = list(outputs)
        self.calls: list[tuple[list[str], str, str, dict[str, str]]] = []

    def __call__(self, cmd, stdin, cwd, env, timeout):
        self.calls.append((cmd, stdin, cwd, env))
        out = self.outputs.pop(0)
        if isinstance(out, Exception):
            raise out
        code, body = out
        return subprocess.CompletedProcess(cmd, code, stdout=json.dumps(body), stderr="")


@pytest.fixture(autouse=True)
def fake_claude_on_path(monkeypatch):
    monkeypatch.setattr("patchpilot.llm.claude_code.shutil.which", lambda exe: f"/usr/bin/{exe}")


def make(runner, **kw):
    return ClaudeCodeProvider("claude-haiku-5-5", runner=runner, sleep=lambda s: None, **kw)


def test_structured_answer_usage_and_isolation(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-should-never-be-used")
    runner = FakeRunner((0, OK))
    resp = make(runner).generate("SYS", "PROMPT", {"type": "object"})
    assert json.loads(resp.text) == {"a": 1}
    assert (resp.usage.prompt_tokens, resp.usage.completion_tokens, resp.usage.cost_usd) == (
        125,
        40,
        0.0012,
    )
    cmd, stdin, _cwd, env = runner.calls[0]
    assert stdin == "PROMPT"  # long prompts go through stdin, not argv
    assert cmd[cmd.index("--tools") + 1] == "" and "--no-session-persistence" in cmd
    assert cmd[cmd.index("--system-prompt") + 1] == "SYS" and "--json-schema" in cmd
    assert "ANTHROPIC_API_KEY" not in env  # never bill an API account behind the user's back


def test_usage_limit_is_quota_not_retried():
    runner = FakeRunner(
        (
            1,
            {
                "is_error": True,
                "subtype": "error",
                "result": "Claude AI usage limit reached|1730000000",
            },
        )
    )
    with pytest.raises(LLMQuotaExhausted, match="not falling back"):
        make(runner).generate("s", "p")
    assert len(runner.calls) == 1


def test_success_mentioning_limits_is_not_a_quota_error():
    body = dict(OK, result="usage limit reached", structured_output=None)
    resp = make(FakeRunner((0, body))).generate("s", "p")
    assert resp.text == "usage limit reached"


def test_transient_errors_retry_then_fail():
    err = (
        1,
        {"is_error": True, "subtype": "error", "result": "overloaded", "api_error_status": 529},
    )
    runner = FakeRunner(err, (0, OK))
    assert make(runner).generate("s", "p", {"type": "object"}).usage.errors == 1
    with pytest.raises(LLMError, match="529"):
        make(FakeRunner(err, err, err)).generate("s", "p")


def test_auth_errors_fail_fast_and_timeouts_raise():
    runner = FakeRunner(
        (
            1,
            {
                "is_error": True,
                "subtype": "error",
                "result": "not logged in",
                "api_error_status": 401,
            },
        )
    )
    with pytest.raises(LLMError, match="401"):
        make(runner).generate("s", "p")
    assert len(runner.calls) == 1
    timeout = subprocess.TimeoutExpired("claude", 1)
    with pytest.raises(LLMTimeout):
        make(FakeRunner(timeout, timeout, timeout)).generate("s", "p")
