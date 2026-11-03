"""Build a provider from a "provider:model" spec.

gemini:gemini-2.5-flash        Google Gemini API (free tier key in GEMINI_API_KEY)
claude-code:claude-haiku-5-5   Claude via the Claude Code CLI (uses a Claude subscription)
"""

from __future__ import annotations

from pathlib import Path

from patchpilot.llm.provider import (
    DEFAULT_GEMINI_MODEL,
    CachingProvider,
    GeminiProvider,
    LLMError,
    LLMProvider,
)

DEFAULT_MODEL_SPEC = f"gemini:{DEFAULT_GEMINI_MODEL}"


def make_provider(
    spec: str = DEFAULT_MODEL_SPEC,
    cache_dir: Path | None = None,
    requests_per_minute: float = 8.0,
) -> LLMProvider:
    kind, _, model = spec.partition(":")
    provider: LLMProvider
    if kind == "gemini":
        provider = GeminiProvider(
            model or DEFAULT_GEMINI_MODEL, requests_per_minute=requests_per_minute
        )
    elif kind == "claude-code":
        from patchpilot.llm.claude_code import ClaudeCodeProvider

        provider = ClaudeCodeProvider(model or "claude-haiku-5-5")
    else:
        raise LLMError(f"unknown provider {kind!r} in {spec!r} (supported: gemini, claude-code)")
    return CachingProvider(provider, cache_dir) if cache_dir is not None else provider
