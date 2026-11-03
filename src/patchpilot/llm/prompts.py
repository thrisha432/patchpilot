"""Prompt construction. Kept separate so prompts are reviewable (and testable) as text."""

from __future__ import annotations

from typing import Any

from patchpilot.models import DocChunk, Finding

EDITS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "edits": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "finding_ids": {"type": "array", "items": {"type": "string"}},
                    "search": {"type": "string"},
                    "replace": {"type": "string"},
                    "explanation": {"type": "string"},
                },
                "required": ["finding_ids", "search", "replace", "explanation"],
            },
        },
        "notes": {"type": "string"},
    },
    "required": ["edits", "notes"],
}

FILE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"content": {"type": "string"}},
    "required": ["content"],
}

SYSTEM = """You are PatchPilot, a careful code-migration engineer.

You migrate ONE Python file at a time by proposing search/replace edits.

Rules for every edit:
1. `search` is copied EXACTLY from the current file: same characters, same indentation,
   one or more complete lines. It must occur exactly once in the file. Include enough
   surrounding lines to make it unique, but keep it small.
2. `replace` is the full replacement for those lines, correctly indented.
3. Edits are applied in order; a later edit sees the result of earlier ones. Never let two
   edits overlap.
4. Change only what the listed findings require, plus the imports those changes need.
   Do not reformat, rename, reorder, or "improve" anything else. Preserve behavior exactly.
5. Update imports: add new names you use (e.g. ConfigDict, field_validator) and remove
   names that are no longer used.
6. `finding_ids` lists the finding ids an edit addresses; `explanation` says why, citing
   the documentation when it applies.
7. Findings marked [needs-check] may be false positives: only change them if the code
   shows the receiver really is a Pydantic model.
8. If a finding needs no change, leave it out and say why in `notes`.

Respond with JSON only, matching the schema."""


def _findings_block(findings: list[Finding]) -> str:
    lines = []
    for f in findings:
        tag = " [needs-check]" if f.confidence.value != "high" else ""
        lines.append(
            f"- id: {f.id}{tag}\n  line {f.line}: {f.message}\n  code:\n{_indent(f.snippet, 4)}"
        )
    return "\n".join(lines)


def _docs_block(docs: list[DocChunk]) -> str:
    if not docs:
        return "(no documentation retrieved)"
    return "\n\n".join(f"### {d.heading}  [{d.id}]\n{d.text}" for d in docs)


def _indent(text: str, n: int) -> str:
    pad = " " * n
    return "\n".join(pad + line for line in text.splitlines())


def patch_prompt(
    profile_title: str,
    profile_hint: str,
    path: str,
    content: str,
    findings: list[Finding],
    docs: list[DocChunk],
    repository_notes: str = "",
) -> str:
    parts = [
        f"Migration: {profile_title}. {profile_hint}",
        f"File: {path}",
    ]
    if repository_notes:
        parts.append(f"Repository context:\n{repository_notes}")
    parts += [
        f"Findings to fix in this file:\n{_findings_block(findings)}",
        f"Relevant migration documentation:\n{_docs_block(docs)}",
        f"Current content of {path}:\n```python\n{content}\n```",
        "Return the edits as JSON.",
    ]
    return "\n\n".join(parts)


def repair_prompt(
    profile_title: str,
    profile_hint: str,
    path: str,
    content: str,
    findings: list[Finding],
    docs: list[DocChunk],
    failure: str,
    repository_notes: str = "",
) -> str:
    parts = [
        f"Migration: {profile_title}. {profile_hint}",
        f"File: {path}",
        "A previous migration attempt was applied to this file and FAILED validation. "
        "The current content below already includes the previous edits. Propose new edits "
        "against this current content that fix the failure. Do not undo correct migrations.",
        f"Failure details:\n{failure}",
    ]
    if repository_notes:
        parts.append(f"Repository context:\n{repository_notes}")
    parts += [
        f"Original findings for this file:\n{_findings_block(findings)}",
        f"Relevant migration documentation:\n{_docs_block(docs)}",
        f"Current content of {path}:\n```python\n{content}\n```",
        "Return the edits as JSON.",
    ]
    return "\n\n".join(parts)


DIRECT_SYSTEM = """You are an expert Python engineer. Return JSON only, matching the schema."""


def direct_prompt(profile_title: str, path: str, content: str) -> str:
    """The baseline: what a developer gets by pasting a file into a chat window."""
    return (
        f"Migrate this file for the migration: {profile_title}.\n"
        f"Return the complete updated file in `content`.\n\n"
        f"File: {path}\n```python\n{content}\n```"
    )
