"""Test-driven discovery: turn unexplained test failures into findings.

Static rules only see the API usages they recognize. Some usages slip past
them (a method passed by reference, a validator applied without decorator
syntax), and some migrations change *behavior* with no API change at all (Pydantic v2 rejects 3.7 for an `int`
field; v1 truncated it). The baseline run of the repository's own tests on the
target version catches those: if a failure's traceback ends in repository code
that no static finding covers, that location becomes a finding, and it goes
through the same retrieve -> patch -> validate loop as any other.
"""

from __future__ import annotations

import re
from pathlib import Path

from tree_sitter import Node

from patchpilot.analyzer.parser import end_line, parse, start_line, walk
from patchpilot.models import AnalysisReport, Confidence, Finding, ValidationResult

_FRAME = re.compile(r"^(?P<path>[\w./-]+\.py):(?P<line>\d+):", re.M)
MAX_SPAN_LINES = 30


def _span(source: bytes, line: int) -> tuple[int, int]:
    """The innermost function containing the line (or just the line if it is too long)."""
    best: Node | None = None
    for node in walk(parse(source).root_node):
        if node.type == "function_definition" and start_line(node) <= line <= end_line(node):
            best = node  # pre-order: later matches are nested deeper
    if best is not None and end_line(best) - start_line(best) < MAX_SPAN_LINES:
        return start_line(best), end_line(best)
    return line, line


def _error_summary(message: str) -> str:
    lines = [ln[1:].strip() for ln in message.splitlines() if ln.startswith("E ")]
    return " ".join(lines[:4])[:400] if lines else (message.splitlines() or [""])[0][:200]


def _covered_lines(analysis: AnalysisReport, root: Path) -> set[tuple[str, int]]:
    """Lines static findings already explain: their spans, plus the header line of any
    class whose body holds a finding (class-creation errors, e.g. a deprecated
    `class Config`, are reported at the `class X(BaseModel):` line)."""
    covered = {(f.file, n) for f in analysis.actionable() for n in range(f.line, f.end_line + 1)}
    for path in {f.file for f in analysis.actionable()}:
        lines = {n for p, n in covered if p == path}
        for node in walk(parse((root / path).read_bytes()).root_node):
            if node.type == "class_definition" and any(
                start_line(node) < n <= end_line(node) for n in lines
            ):
                covered.add((path, start_line(node)))
    return covered


def discover(validation: ValidationResult, analysis: AnalysisReport, root: Path) -> list[Finding]:
    sources = {f.path for f in analysis.files if not f.is_test}
    covered = _covered_lines(analysis, root)
    found: dict[tuple[str, int], Finding] = {}
    for test in validation.tests:
        if test.outcome not in ("failed", "error"):
            continue
        frames = [
            (m["path"], int(m["line"]))
            for m in _FRAME.finditer(test.message)
            if m["path"] in sources
        ]
        if not frames:
            continue
        path, line = frames[-1]  # deepest frame in repository (non-test) code
        if (path, line) in covered or (path, line) in found:
            continue
        source = (root / path).read_bytes()
        first, last = _span(source, line)
        snippet = "\n".join(source.decode("utf-8", errors="replace").splitlines()[first - 1 : last])
        error = _error_summary(test.message)
        found[(path, line)] = Finding(
            id=f"{path}:{line}:test-failure",
            rule="test-failure",
            title="Fails on the target version (found by running the tests)",
            file=path,
            line=first,  # the enclosing function: what an edit may touch
            end_line=last,
            snippet=snippet,
            message=f"`{test.nodeid}` fails on the target version at line {line}: {error}. "
            "Static analysis found nothing here: either a behavior change or a usage it "
            "could not recognize.",
            confidence=Confidence.HIGH,
            symbols=tuple(dict.fromkeys(re.findall(r"[A-Za-z_]{4,}", error)))[:12],
        )
    return list(found.values())
