"""Split Markdown migration guides into heading-scoped chunks.

A chunk is one section (heading + body up to the next heading of any level),
labelled with its full heading path so the LLM and the report can cite it as
"Migration guide > Changes to config". ``#`` lines inside fenced code blocks
are code comments, not headings, and do not start a chunk.
"""

from __future__ import annotations

import re
from pathlib import Path

from patchpilot.models import DocChunk

_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
_FENCE = re.compile(r"^\s*(```|~~~)")
MAX_CHUNK_CHARS = 2400  # longer sections are split on paragraph boundaries


def slugify(heading: str) -> str:
    slug = re.sub(r"[^\w\s-]", "", heading.lower()).strip()
    return re.sub(r"[\s_]+", "-", slug)


def chunk_markdown(markdown: str, source: str) -> list[DocChunk]:
    chunks: list[DocChunk] = []
    path: list[tuple[int, str]] = []  # (level, heading)
    body: list[str] = []
    in_fence = False
    seen: dict[str, int] = {}

    def flush() -> None:
        content = "\n".join(body).strip()
        if not content or not path:
            return
        heading = " > ".join(h for _, h in path)
        base = f"{source}#{slugify(path[-1][1])}"
        for part in _split(content):
            n = seen.get(base, 0) + 1
            seen[base] = n
            chunks.append(
                DocChunk(
                    id=base if n == 1 else f"{base}-{n}",
                    source=source,
                    heading=heading,
                    text=part,
                )
            )

    for line in markdown.splitlines():
        if _FENCE.match(line):
            in_fence = not in_fence
            body.append(line)
            continue
        m = None if in_fence else _HEADING.match(line)
        if m is None:
            body.append(line)
            continue
        flush()
        body = []
        level, heading = len(m.group(1)), m.group(2).strip()
        while path and path[-1][0] >= level:
            path.pop()
        path.append((level, heading))
    flush()
    return chunks


def _split(content: str) -> list[str]:
    if len(content) <= MAX_CHUNK_CHARS:
        return [content]
    """Split at a blank line or a list item once the budget is reached, never inside a code block."""
    parts: list[str] = []
    current: list[str] = []
    size = 0
    in_fence = False
    for line in content.splitlines():
        boundary = not line.strip() or line.lstrip().startswith(("* ", "- ", "| "))
        if size >= MAX_CHUNK_CHARS * 0.75 and boundary and not in_fence and current:
            parts.append("\n".join(current).strip())
            current, size = [], 0
        if _FENCE.match(line):
            in_fence = not in_fence
        current.append(line)
        size += len(line) + 1
    if "".join(current).strip():
        parts.append("\n".join(current).strip())
    return parts


def load_guides(directory: Path) -> list[DocChunk]:
    chunks: list[DocChunk] = []
    for path in sorted(directory.glob("*.md")):
        chunks.extend(chunk_markdown(path.read_text(encoding="utf-8"), path.name))
    return chunks
