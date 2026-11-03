"""Apply search/replace edits safely. Pure functions: text in, text out.

Why search/replace instead of unified diffs: LLMs routinely get diff line
numbers and hunk headers wrong, and a diff that "applies with fuzz" can land
in the wrong place. An exact-text anchor that must match exactly once cannot
land in the wrong place; if it matches zero or several times, the edit is
rejected with a reason the repair step can act on.
"""

from __future__ import annotations

import difflib
from dataclasses import dataclass

from patchpilot.analyzer.parser import end_line, parse
from patchpilot.models import Edit, EditOutcome

SCOPE_MARGIN = 2  # lines of slack around a finding's span
MAX_EDIT_FRACTION = 0.6  # an edit may not replace more than 60% of a file (> 30 lines)


@dataclass(frozen=True)
class LineRange:
    start: int  # 1-based inclusive
    end: int  # 1-based inclusive

    def overlaps(self, other: LineRange) -> bool:
        return self.start <= other.end and other.start <= self.end


def _lines_keepends(text: str) -> list[str]:
    return text.splitlines(keepends=True)


def _find_exact(content: str, search: str) -> list[int]:
    """Character offsets of every occurrence of search (non-overlapping)."""
    hits, start = [], 0
    while (i := content.find(search, start)) != -1:
        hits.append(i)
        start = i + max(1, len(search))
    return hits


def _find_loose(lines: list[str], search_lines: list[str]) -> tuple[list[int], str]:
    """Line-window matches ignoring trailing whitespace, then ignoring a uniform indent shift.

    Returns (start indices of matches, mode) where mode is "fuzzy-whitespace" or
    "fuzzy-indent:<delta>"; for indent matches, all hits share one delta.
    """
    n = len(search_lines)
    target = [s.rstrip() for s in search_lines]
    hits = [
        i for i in range(len(lines) - n + 1) if [ln.rstrip() for ln in lines[i : i + n]] == target
    ]
    if hits:
        return hits, "fuzzy-whitespace"

    def strip_common(block: list[str]) -> tuple[list[str], int]:
        widths = [len(b) - len(b.lstrip()) for b in block if b.strip()]
        w = min(widths) if widths else 0
        return [b[w:].rstrip() if b.strip() else "" for b in block], w

    target_d, target_w = strip_common(search_lines)
    found: list[int] = []
    delta = 0
    for i in range(len(lines) - n + 1):
        window, w = strip_common(lines[i : i + n])
        if window == target_d:
            found.append(i)
            delta = w - target_w
    return found, f"fuzzy-indent:{delta}"


def _reindent(text: str, delta: int) -> str:
    if delta == 0:
        return text
    out = []
    for line in text.splitlines(keepends=True):
        if not line.strip():
            out.append(line)
        elif delta > 0:
            out.append(" " * delta + line)
        else:
            cut = min(-delta, len(line) - len(line.lstrip()))
            out.append(line[cut:])
    return "".join(out)


def locate(content: str, search: str) -> tuple[int, int, str, str] | str:
    """Find search in content. Returns (start_char, end_char, mode, matched_text) or a reason."""
    if not search.strip():
        return "empty search text"
    hits = _find_exact(content, search)
    if len(hits) == 1:
        return hits[0], hits[0] + len(search), "exact", search
    if len(hits) > 1:
        return f"ambiguous: search text occurs {len(hits)} times"
    lines = _lines_keepends(content)
    search_lines = search.splitlines()
    if search.endswith("\n"):
        pass  # splitlines already dropped the final empty element
    if not search_lines:
        return "empty search text"
    starts, mode = _find_loose(lines, search_lines)
    if len(starts) != 1:
        return (
            "search text not found in the current file"
            if not starts
            else f"ambiguous: search text matches {len(starts)} places (ignoring whitespace)"
        )
    i = starts[0]
    begin = sum(len(ln) for ln in lines[:i])
    matched = "".join(lines[i : i + len(search_lines)])
    return begin, begin + len(matched), mode, matched


def apply_edit(content: str, edit: Edit, scope: list[LineRange] | None) -> tuple[str, EditOutcome]:
    """Apply one edit, or reject it. ``scope`` (current-file line ranges) limits where it may land."""
    found = locate(content, edit.search)
    if isinstance(found, str):
        return content, EditOutcome(edit=edit, applied=False, reason=found)
    begin, end, mode, matched = found
    start_line = content.count("\n", 0, begin) + 1
    end_line_ = start_line + max(matched.count("\n") - (1 if matched.endswith("\n") else 0), 0)
    total = content.count("\n") + 1
    if total > 30 and (end_line_ - start_line + 1) > MAX_EDIT_FRACTION * total:
        return content, EditOutcome(
            edit=edit,
            applied=False,
            reason=f"too large: replaces {end_line_ - start_line + 1} of {total} lines",
            start_line=start_line,
        )
    if scope is not None:
        region = LineRange(start_line, end_line_)
        if not any(region.overlaps(r) for r in scope):
            return content, EditOutcome(
                edit=edit,
                applied=False,
                reason=f"out of scope: lines {start_line}-{end_line_} are not near any finding or the imports",
                start_line=start_line,
            )
    replace = edit.replace
    if mode.startswith("fuzzy-indent:"):
        replace = _reindent(replace, int(mode.split(":", 1)[1]))
    if matched.endswith("\n") and replace and not replace.endswith("\n"):
        replace += "\n"
    new = content[:begin] + replace + content[end:]
    if new == content:
        return content, EditOutcome(
            edit=edit, applied=False, reason="no-op: replacement is identical"
        )
    return new, EditOutcome(
        edit=edit, applied=True, reason="" if mode == "exact" else mode, start_line=start_line
    )


def import_block_end(content: str) -> int:
    """Last line of the module's leading block of docstring/comments/imports (0 if none)."""
    root = parse(content.encode()).root_node
    last = 0
    for stmt in root.named_children:
        is_doc = (
            stmt.type == "expression_statement"
            and stmt.named_children
            and stmt.named_children[0].type == "string"
        )
        if stmt.type in (
            "import_statement",
            "import_from_statement",
            "future_import_statement",
            "comment",
        ) or (is_doc and last == 0):
            last = end_line(stmt)
            continue
        if (
            stmt.type == "if_statement"
            and "TYPE_CHECKING" in (stmt.text or b"").decode(errors="replace")[:60]
        ):
            last = end_line(stmt)
            continue
        break
    return last


def map_range(original: str, current: str, r: LineRange) -> LineRange:
    """Where original lines r.start..r.end are now, after edits (via a line diff)."""
    a, b = original.splitlines(), current.splitlines()
    matcher = difflib.SequenceMatcher(a=a, b=b, autojunk=False)

    def map_line(line: int, prefer_end: bool) -> int:
        idx = line - 1
        for tag, i1, i2, j1, j2 in matcher.get_opcodes():
            if i1 <= idx < i2 or (tag == "insert" and i1 == idx):
                if tag == "equal":
                    return j1 + (idx - i1) + 1
                return (j2 if prefer_end else j1 + 1) if j2 > j1 else j1 + 1
        return len(b)

    start = map_line(r.start, prefer_end=False)
    end = max(start, map_line(r.end, prefer_end=True))
    return LineRange(start, end)


def scope_for(original: str, current: str, spans: list[LineRange]) -> list[LineRange]:
    ranges = [map_range(original, current, s) for s in spans]
    ranges = [LineRange(max(1, r.start - SCOPE_MARGIN), r.end + SCOPE_MARGIN) for r in ranges]
    imports_end = import_block_end(current)
    ranges.append(LineRange(1, imports_end + 1))  # imports, plus one line to append after them
    return ranges
