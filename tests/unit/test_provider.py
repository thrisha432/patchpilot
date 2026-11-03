"""Gemini provider against a mocked HTTP transport: parsing, retries, quota, key safety."""

from __future__ import annotations

import json

import httpx
import pytest

from patchpilot.llm.patch_generator import request_edits, request_full_file
from patchpilot.llm.provider import (
    CachingProvider,
    GeminiProvider,
    LLMBadResponse,
    LLMError,
    LLMQuotaExhausted,
    LLMTimeout,
    ScriptedProvider,
    _RateLimiter,
    load_api_key,
)

KEY = "test-key-123"


def ok_body(text: str, thoughts: int = 0) -> dict:
    return {
        "candidates": [
            {
                "content": {"parts": [{"text": "(thinking)", "thought": True}, {"text": text}]},
                "finishReason": "STOP",
            }
        ],
        "usageMetadata": {
            "promptTokenCount": 100,
            "candidatesTokenCount": 20,
            "thoughtsTokenCount": thoughts,
        },
    }


def provider(handler, **kw) -> tuple[GeminiProvider, list[float]]:
    sleeps: list[float] = []
    p = GeminiProvider(
        "gemini-test",
        api_key=KEY,
        requests_per_minute=0,
        transport=httpx.MockTransport(handler),
        sleep=sleeps.append,
        **kw,
    )
    return p, sleeps


def test_success_parses_text_usage_and_request_shape():
    seen: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        return httpx.Response(200, json=ok_body('{"a": 1}', thoughts=5))

    p, _ = provider(handler)
    resp = p.generate("sys", "prompt", {"type": "object"})
    assert resp.text == '{"a": 1}'  # thought parts are excluded
    assert (resp.usage.prompt_tokens, resp.usage.completion_tokens, resp.usage.calls) == (
        100,
        25,
        1,
    )
    req = seen[0]
    assert req.url.path.endswith("/models/gemini-test:generateContent")
    assert KEY not in str(req.url) and req.headers["x-goog-api-key"] == KEY  # key never in the URL
    body = json.loads(req.content)
    assert body["generationConfig"]["responseMimeType"] == "application/json"
    assert body["generationConfig"]["temperature"] == 0.0
    assert body["systemInstruction"]["parts"][0]["text"] == "sys"


def test_rate_limit_retries_after_server_delay():
    calls = iter(
        [
            httpx.Response(429, json={"error": {"status": "RESOURCE_EXHAUSTED", "details": [{"retryDelay": "7s"}], "message": "per minute"}}),
            httpx.Response(200, json=ok_body("{}")),
        ]
    )  # fmt: skip
    p, sleeps = provider(lambda req: next(calls))
    resp = p.generate("s", "p")
    assert resp.text == "{}" and sleeps == [7.0] and resp.usage.errors == 1


def test_daily_quota_is_not_retried_and_never_falls_back():
    count = {"n": 0}

    def handler(req: httpx.Request) -> httpx.Response:
        count["n"] += 1
        return httpx.Response(
            429,
            json={
                "error": {
                    "message": "Quota exceeded for metric generate_content_free_tier_requests, limit: PerDay"
                }
            },
        )

    p, sleeps = provider(handler)
    with pytest.raises(LLMQuotaExhausted, match="not switching to a paid model"):
        p.generate("s", "p")
    assert count["n"] == 1 and sleeps == []


def test_server_errors_retry_then_give_up():
    p, sleeps = provider(
        lambda req: httpx.Response(503, json={"error": {"message": "overloaded"}}), max_retries=2
    )
    with pytest.raises(LLMError, match="503 after 3 attempts"):
        p.generate("s", "p")
    assert len(sleeps) == 2


def test_client_errors_fail_fast():
    p, sleeps = provider(lambda req: httpx.Response(400, json={"error": {"message": "bad schema"}}))
    with pytest.raises(LLMError, match="400: bad schema"):
        p.generate("s", "p")
    assert sleeps == []


def test_timeouts_retry_then_raise():
    def handler(req: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=req)

    p, _ = provider(handler, max_retries=1)
    with pytest.raises(LLMTimeout):
        p.generate("s", "p")


@pytest.mark.parametrize(
    ("body", "match"),
    [
        ({"candidates": [], "promptFeedback": {"blockReason": "SAFETY"}}, "SAFETY"),
        (
            {"candidates": [{"content": {"parts": [{"text": "{"}]}, "finishReason": "MAX_TOKENS"}]},
            "MAX_TOKENS",
        ),
    ],
)
def test_blocked_or_truncated_answers(body, match):
    p, _ = provider(lambda req: httpx.Response(200, json=body))
    with pytest.raises(LLMBadResponse, match=match):
        p.generate("s", "p")


def test_missing_key_explains_how_to_get_one(monkeypatch, tmp_path):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.chdir(tmp_path)
    with pytest.raises(LLMError, match=r"aistudio\.google\.com"):
        GeminiProvider()


def test_load_api_key_from_dotenv(monkeypatch, tmp_path):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    env = tmp_path / ".env"
    env.write_text("OTHER=1\nGEMINI_API_KEY='abc'\n")
    assert load_api_key(dotenv=env) == "abc"


def test_rate_limiter_spaces_requests():
    now = {"t": 100.0}
    sleeps: list[float] = []
    limiter = _RateLimiter(per_minute=30, clock=lambda: now["t"])
    for _ in range(3):
        limiter.wait(sleeps.append)
    assert sleeps == [2.0, 4.0]


def test_caching_provider_replays_without_calling(tmp_path):
    inner = ScriptedProvider(["one"])
    cache = CachingProvider(inner, tmp_path)
    first = cache.generate("s", "p", None)
    second = cache.generate("s", "p", None)  # ScriptedProvider would raise if called again
    assert (first.text, first.cached, second.text, second.cached) == ("one", False, "one", True)
    assert second.usage == first.usage


EDITS = json.dumps(
    {
        "edits": [{"finding_ids": ["f1"], "search": "a", "replace": "b", "explanation": "e"}],
        "notes": "n",
    }
)


def test_request_edits_strips_fences_and_retries_invalid_json():
    p = ScriptedProvider(["not json", f"```json\n{EDITS}\n```"])
    answer = request_edits(p, "prompt")
    assert answer.error == "" and answer.edits[0].replace == "b" and answer.usage.calls == 2
    assert "not valid JSON" in p.calls[1][1]


def test_request_edits_reports_persistent_garbage_and_llm_errors():
    assert "invalid JSON" in request_edits(ScriptedProvider(["x", "y"]), "p").error
    answer = request_edits(ScriptedProvider([LLMTimeout("slow")]), "p")
    assert answer.error.startswith("LLMTimeout") and answer.usage.errors == 1


def test_request_full_file():
    content, usage, err = request_full_file(
        ScriptedProvider([json.dumps({"content": "x = 1\n"})]), "s", "p"
    )
    assert (content, err, usage.calls) == ("x = 1\n", "", 1)
    content, _, err = request_full_file(ScriptedProvider([LLMError("down")]), "s", "p")
    assert content is None and "down" in err
