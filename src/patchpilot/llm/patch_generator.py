"""Ask the LLM for search/replace edits for one file, and parse the answer strictly."""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from pydantic import BaseModel, ValidationError

from patchpilot.llm.prompts import EDITS_SCHEMA, FILE_SCHEMA, SYSTEM
from patchpilot.llm.provider import LLMError, LLMProvider
from patchpilot.models import Edit, LLMUsage


class _EditsAnswer(BaseModel):
    edits: list[Edit]
    notes: str = ""


class _FileAnswer(BaseModel):
    content: str


@dataclass
class PatchAnswer:
    edits: list[Edit] = field(default_factory=list)
    notes: str = ""
    error: str = ""
    usage: LLMUsage = field(default_factory=LLMUsage)


def _strip_fences(text: str) -> str:
    """Models sometimes wrap JSON in ```json fences even when asked not to."""
    t = text.strip()
    if t.startswith("```"):
        t = t.split("\n", 1)[1] if "\n" in t else ""
        if t.rstrip().endswith("```"):
            t = t.rstrip()[:-3]
    return t.strip()


def request_edits(provider: LLMProvider, prompt: str, system: str = SYSTEM) -> PatchAnswer:
    """One LLM call; one retry if the answer is not valid JSON for the schema."""
    answer = PatchAnswer()
    for attempt in range(2):
        try:
            resp = provider.generate(system, prompt, EDITS_SCHEMA)
        except LLMError as exc:
            answer.usage.errors += 1
            answer.error = f"{type(exc).__name__}: {exc}"
            return answer
        answer.usage.add(resp.usage)
        try:
            parsed = _EditsAnswer.model_validate(json.loads(_strip_fences(resp.text)))
        except (json.JSONDecodeError, ValidationError) as exc:
            answer.error = f"invalid JSON from model: {str(exc).splitlines()[0][:200]}"
            if attempt == 0:
                prompt += (
                    "\n\nYour previous answer was not valid JSON for the schema. "
                    "Answer again with JSON only."
                )
                continue
            return answer
        answer.edits, answer.notes, answer.error = parsed.edits, parsed.notes, ""
        return answer
    return answer


def request_full_file(
    provider: LLMProvider, system: str, prompt: str
) -> tuple[str | None, LLMUsage, str]:
    """Baseline: ask for the whole rewritten file. Returns (content, usage, error)."""
    usage = LLMUsage()
    try:
        resp = provider.generate(system, prompt, FILE_SCHEMA)
    except LLMError as exc:
        usage.errors += 1
        return None, usage, f"{type(exc).__name__}: {exc}"
    usage.add(resp.usage)
    try:
        return _FileAnswer.model_validate(json.loads(_strip_fences(resp.text))).content, usage, ""
    except (json.JSONDecodeError, ValidationError) as exc:
        return None, usage, f"invalid JSON from model: {str(exc).splitlines()[0][:200]}"
