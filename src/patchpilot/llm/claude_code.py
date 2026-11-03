"""Claude models through the Claude Code CLI in headless mode (``claude -p``).

This runs under the user's Claude subscription instead of an API key, so it
costs nothing extra; it is bounded by the subscription's usage limits instead.
Each call is a fresh, tool-less, session-less CLI invocation in an empty
directory, so no project files, CLAUDE.md, MCP servers, or tools are involved:
it is a plain prompt -> JSON answer, exactly like the Gemini provider.

``ANTHROPIC_API_KEY`` is removed from the child environment on purpose: if it
were set, the CLI would bill that API account instead of the subscription.
Reaching the subscription's usage limit raises LLMQuotaExhausted (no fallback).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import time
from collections.abc import Callable
from typing import Any

from patchpilot.llm.provider import (
    LLMBadResponse,
    LLMError,
    LLMQuotaExhausted,
    LLMResponse,
    LLMTimeout,
)
from patchpilot.models import LLMUsage

Runner = Callable[[list[str], str, str, dict[str, str], float], subprocess.CompletedProcess[str]]
_BILLING_VARS = (
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_AUTH_TOKEN",
    "CLAUDE_CODE_USE_BEDROCK",
    "CLAUDE_CODE_USE_VERTEX",
)


def _run(
    cmd: list[str], stdin: str, cwd: str, env: dict[str, str], timeout: float
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        input=stdin,
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


class ClaudeCodeProvider:
    def __init__(
        self,
        model: str = "claude-haiku-5-5",
        executable: str = "claude",
        timeout_s: float = 300.0,
        max_retries: int = 2,
        runner: Runner = _run,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        exe = shutil.which(executable)
        if exe is None:
            raise LLMError("Claude Code CLI (`claude`) not found on PATH")
        self.model = model
        self._exe = exe
        self._timeout = timeout_s
        self._max_retries = max_retries
        self._runner = runner
        self._sleep = sleep
        self._cwd = tempfile.mkdtemp(prefix="patchpilot-claude-")  # empty: nothing to read

    @property
    def name(self) -> str:
        return f"claude-code:{self.model}"

    def command(self, system: str, schema: dict[str, Any] | None) -> list[str]:
        cmd = [
            self._exe, "-p",
            "--model", self.model,
            "--output-format", "json",
            "--tools", "",
            "--no-session-persistence",
            "--setting-sources", "",
            "--strict-mcp-config",
            "--system-prompt", system,
        ]  # fmt: skip
        if schema is not None:
            cmd += ["--json-schema", json.dumps(schema)]
        return cmd

    def generate(
        self, system: str, prompt: str, schema: dict[str, Any] | None = None
    ) -> LLMResponse:
        env = {k: v for k, v in os.environ.items() if k not in _BILLING_VARS}
        errors = 0
        for attempt in range(self._max_retries + 1):
            started = time.monotonic()
            try:
                proc = self._runner(
                    self.command(system, schema), prompt, self._cwd, env, self._timeout
                )
            except subprocess.TimeoutExpired as exc:
                errors += 1
                if attempt == self._max_retries:
                    raise LLMTimeout(f"claude -p timed out after {self._timeout:.0f}s") from exc
                continue
            elapsed = time.monotonic() - started
            try:
                data = json.loads(proc.stdout)
            except json.JSONDecodeError:
                data = {}
            failed = (
                proc.returncode != 0 or data.get("is_error") or data.get("subtype") != "success"
            )
            if failed:
                text = str(data.get("result") or proc.stderr or proc.stdout)[:500]
                lowered = text.lower()
                # Only inspect the text of a *failed* call: a successful answer may mention limits.
                if "usage limit" in lowered or "limit reached" in lowered:
                    raise LLMQuotaExhausted(
                        f"Claude subscription usage limit reached; not falling back. ({text[:200]})"
                    )
                errors += 1
                status = data.get("api_error_status")
                if attempt == self._max_retries or status in (400, 401, 403):
                    raise LLMError(
                        f"claude -p failed (exit {proc.returncode}, status {status}): {text[:300]}"
                    )
                self._sleep(min(5 * 2**attempt, 60))
                continue
            return self._parse(data, elapsed, errors, schema is not None)
        raise LLMError("unreachable")  # pragma: no cover

    def _parse(
        self, data: dict[str, Any], elapsed: float, errors: int, structured: bool
    ) -> LLMResponse:
        u = data.get("usage") or {}
        usage = LLMUsage(
            calls=1,
            prompt_tokens=int(u.get("input_tokens", 0))
            + int(u.get("cache_creation_input_tokens", 0))
            + int(u.get("cache_read_input_tokens", 0)),
            completion_tokens=int(u.get("output_tokens", 0)),
            seconds=round(elapsed, 3),
            errors=errors,
            cost_usd=float(data.get("total_cost_usd") or 0.0),
        )
        if structured:
            if data.get("structured_output") is None:
                raise LLMBadResponse("no structured output in the answer")
            return LLMResponse(text=json.dumps(data["structured_output"]), usage=usage)
        return LLMResponse(text=str(data.get("result", "")), usage=usage)
