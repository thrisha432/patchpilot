"""LLM providers behind one small interface.

The pipeline only ever calls ``provider.generate(system, prompt, schema)``.
Swapping models means writing one class, not touching the pipeline.

Providers here:
* ``GeminiProvider``: Google's Gemini API over plain HTTPS (free tier by default).
  It never upgrades to a paid model or retries past a daily quota: quota
  exhaustion is an error the run reports, not something to work around.
* ``ClaudeCodeProvider`` (claude_code.py): Claude models through the Claude Code CLI,
  under a Claude subscription instead of an API key.
* ``ScriptedProvider``: deterministic responses for tests (no network, no key).
* ``CachingProvider``: wraps any provider with an on-disk response cache, so
  re-running a benchmark costs no quota and gives identical model output.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import httpx

from patchpilot.models import LLMUsage


class LLMError(Exception):
    """Any failure to get a usable response."""


class LLMTimeout(LLMError):
    pass


class LLMQuotaExhausted(LLMError):
    """The provider's quota (e.g. the free tier's daily limit) is used up. Not retried."""


class LLMBadResponse(LLMError):
    """The model answered, but not with what was asked for (blocked, truncated, not JSON)."""


@dataclass(frozen=True)
class LLMResponse:
    text: str
    usage: LLMUsage
    cached: bool = False


class LLMProvider(Protocol):
    @property
    def name(self) -> str: ...

    def generate(
        self, system: str, prompt: str, schema: dict[str, Any] | None = None
    ) -> LLMResponse: ...


# --------------------------------------------------------------------------------------
# Gemini


GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
DEFAULT_GEMINI_MODEL = "gemini-2.5-flash"


def load_api_key(env: str = "GEMINI_API_KEY", dotenv: Path | None = None) -> str | None:
    """Key from the environment, else from a local .env file (never from code or config)."""
    for name in (env, "GOOGLE_API_KEY"):
        if os.environ.get(name):
            return os.environ[name]
    path = dotenv or Path.cwd() / ".env"
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            key, sep, value = line.partition("=")
            if sep and key.strip() in (env, "GOOGLE_API_KEY") and value.strip():
                return value.strip().strip("'\"")
    return None


class _RateLimiter:
    """Spaces requests at least ``interval`` seconds apart (thread-safe)."""

    def __init__(self, per_minute: float, clock: Callable[[], float] = time.monotonic) -> None:
        self.interval = 60.0 / per_minute if per_minute > 0 else 0.0
        self._clock = clock
        self._next = 0.0
        self._lock = threading.Lock()

    def wait(self, sleep: Callable[[float], None] = time.sleep) -> None:
        with self._lock:
            now = self._clock()
            delay = self._next - now
            self._next = max(now, self._next) + self.interval
        if delay > 0:
            sleep(delay)


def _retry_delay_seconds(body: dict[str, Any]) -> float | None:
    for detail in body.get("error", {}).get("details", []) or []:
        delay = detail.get("retryDelay")
        if isinstance(delay, str) and (m := re.fullmatch(r"([\d.]+)s", delay)):
            return float(m.group(1))
    return None


def _is_daily_quota(body: dict[str, Any]) -> bool:
    text = json.dumps(body.get("error", {}))
    return "PerDay" in text or "per day" in text.lower()


class GeminiProvider:
    def __init__(
        self,
        model: str = DEFAULT_GEMINI_MODEL,
        api_key: str | None = None,
        requests_per_minute: float = 8.0,
        timeout_s: float = 120.0,
        max_retries: int = 4,
        thinking_budget: int | None = None,
        max_output_tokens: int = 8192,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        key = api_key or load_api_key()
        if not key:
            raise LLMError(
                "No Gemini API key: set GEMINI_API_KEY (or put it in a .env file). "
                "Get a free key at https://aistudio.google.com/apikey"
            )
        self.model = model
        self._limiter = _RateLimiter(requests_per_minute)
        self._max_retries = max_retries
        self._thinking_budget = thinking_budget
        self._max_output_tokens = max_output_tokens
        self._sleep = sleep
        # The key travels in a header, never in the URL, so it cannot leak into logs.
        self._client = httpx.Client(
            timeout=httpx.Timeout(timeout_s, connect=10.0),
            headers={"x-goog-api-key": key, "content-type": "application/json"},
            transport=transport,
        )

    @property
    def name(self) -> str:
        return f"gemini:{self.model}"

    def _body(self, system: str, prompt: str, schema: dict[str, Any] | None) -> dict[str, Any]:
        config: dict[str, Any] = {"temperature": 0.0, "maxOutputTokens": self._max_output_tokens}
        if schema is not None:
            config["responseMimeType"] = "application/json"
            config["responseJsonSchema"] = schema
        if self._thinking_budget is not None:
            config["thinkingConfig"] = {"thinkingBudget": self._thinking_budget}
        return {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": config,
        }

    def generate(
        self, system: str, prompt: str, schema: dict[str, Any] | None = None
    ) -> LLMResponse:
        body = self._body(system, prompt, schema)
        url = GEMINI_URL.format(model=self.model)
        errors = 0
        for attempt in range(self._max_retries + 1):
            self._limiter.wait(self._sleep)
            started = time.monotonic()
            try:
                resp = self._client.post(url, json=body)
            except httpx.TimeoutException as exc:
                errors += 1
                if attempt == self._max_retries:
                    raise LLMTimeout(
                        f"Gemini request timed out after {attempt + 1} attempts"
                    ) from exc
                continue
            except httpx.HTTPError as exc:
                errors += 1
                if attempt == self._max_retries:
                    raise LLMError(f"Gemini request failed: {type(exc).__name__}") from exc
                self._sleep(min(2**attempt, 30))
                continue
            elapsed = time.monotonic() - started
            if resp.status_code == 200:
                return self._parse(resp.json(), elapsed, errors)
            payload = _safe_json(resp)
            errors += 1
            if resp.status_code == 429:
                if _is_daily_quota(payload):
                    raise LLMQuotaExhausted(
                        "Gemini free-tier daily quota exhausted; not retrying and not switching "
                        "to a paid model. Try again after the quota resets."
                    )
                delay = _retry_delay_seconds(payload) or min(5 * 2**attempt, 60)
            elif resp.status_code in (500, 502, 503, 504):
                delay = min(2 ** (attempt + 1), 30)
            else:
                message = payload.get("error", {}).get("message", resp.text[:300])
                raise LLMError(f"Gemini API error {resp.status_code}: {message}")
            if attempt == self._max_retries:
                raise LLMError(f"Gemini API error {resp.status_code} after {attempt + 1} attempts")
            self._sleep(delay)
        raise LLMError("unreachable")  # pragma: no cover

    def _parse(self, data: dict[str, Any], elapsed: float, errors: int) -> LLMResponse:
        meta = data.get("usageMetadata", {})
        usage = LLMUsage(
            calls=1,
            prompt_tokens=int(meta.get("promptTokenCount", 0)),
            # Thinking tokens are billed (and count against quotas) like output tokens.
            completion_tokens=int(meta.get("candidatesTokenCount", 0))
            + int(meta.get("thoughtsTokenCount", 0)),
            seconds=round(elapsed, 3),
            errors=errors,
        )
        candidates = data.get("candidates") or []
        if not candidates:
            reason = data.get("promptFeedback", {}).get("blockReason", "no candidates")
            raise LLMBadResponse(f"Gemini returned no answer ({reason})")
        cand = candidates[0]
        parts = cand.get("content", {}).get("parts", []) or []
        text = "".join(p.get("text", "") for p in parts if not p.get("thought"))
        finish = cand.get("finishReason", "STOP")
        if finish not in ("STOP", "FINISH_REASON_UNSPECIFIED"):
            raise LLMBadResponse(f"Gemini stopped early: {finish}")
        return LLMResponse(text=text, usage=usage)


def _safe_json(resp: httpx.Response) -> dict[str, Any]:
    try:
        data = resp.json()
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


# --------------------------------------------------------------------------------------
# Test double and cache


class ScriptedProvider:
    """Returns scripted responses. Each item is text, an exception to raise, or a callable."""

    def __init__(
        self,
        responses: Sequence[str | Exception | Callable[[str, str], str]],
        name: str = "scripted",
    ) -> None:
        self._responses = list(responses)
        self._name = name
        self.calls: list[tuple[str, str]] = []

    @property
    def name(self) -> str:
        return self._name

    def generate(
        self, system: str, prompt: str, schema: dict[str, Any] | None = None
    ) -> LLMResponse:
        self.calls.append((system, prompt))
        if not self._responses:
            raise LLMError("ScriptedProvider ran out of responses")
        item = self._responses.pop(0)
        if isinstance(item, Exception):
            raise item
        text = item(system, prompt) if callable(item) else item
        usage = LLMUsage(calls=1, prompt_tokens=len(prompt) // 4, completion_tokens=len(text) // 4)
        return LLMResponse(text=text, usage=usage)


class CachingProvider:
    """On-disk cache keyed by (model, system, prompt, schema). Stores the original usage."""

    def __init__(self, inner: LLMProvider, directory: Path) -> None:
        self.inner = inner
        self.directory = directory
        directory.mkdir(parents=True, exist_ok=True)

    @property
    def name(self) -> str:
        return self.inner.name

    def _path(self, system: str, prompt: str, schema: dict[str, Any] | None) -> Path:
        key = json.dumps([self.inner.name, system, prompt, schema], sort_keys=True)
        return self.directory / f"{hashlib.sha256(key.encode()).hexdigest()}.json"

    def generate(
        self, system: str, prompt: str, schema: dict[str, Any] | None = None
    ) -> LLMResponse:
        path = self._path(system, prompt, schema)
        if path.is_file():
            data = json.loads(path.read_text(encoding="utf-8"))
            return LLMResponse(text=data["text"], usage=LLMUsage(**data["usage"]), cached=True)
        resp = self.inner.generate(system, prompt, schema)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(
            json.dumps({"text": resp.text, "usage": resp.usage.model_dump()}), encoding="utf-8"
        )
        tmp.replace(path)  # atomic: a crash never leaves a half-written cache entry
        return resp
