"""Retrieve migration-guide sections relevant to each finding."""

from __future__ import annotations

from pathlib import Path

from patchpilot.models import DocChunk, Finding, RetrievedDoc
from patchpilot.retrieval.bm25 import BM25
from patchpilot.retrieval.chunker import load_guides


def finding_query(finding: Finding) -> str:
    """The query is built from the finding itself, not hand-written per rule.

    Symbols (the identifiers involved, e.g. `orm_mode`) are repeated so they
    outweigh the generic words of the message.
    """
    symbols = " ".join(finding.symbols)
    return f"{symbols} {symbols} {finding.title} {finding.message}"


class Retriever:
    def __init__(self, chunks: list[DocChunk]) -> None:
        self.chunks = chunks
        # The heading is part of the indexed text: it is the best summary of a section.
        self.index = BM25([f"{c.heading}\n{c.text}" for c in chunks])

    @classmethod
    def from_directory(cls, directory: Path) -> Retriever:
        return cls(load_guides(directory))

    def search(self, query: str, k: int = 3) -> list[RetrievedDoc]:
        return [
            RetrievedDoc(chunk=self.chunks[i], score=round(s, 3))
            for i, s in self.index.top(query, k)
        ]

    def for_finding(self, finding: Finding, k: int = 3) -> list[RetrievedDoc]:
        return self.search(finding_query(finding), k)


def context_for_file(
    retrieved: dict[str, list[RetrievedDoc]], finding_ids: list[str], budget_chars: int = 7000
) -> list[DocChunk]:
    """Deduplicated chunks for one file's findings, best-ranked first, within a size budget.

    Round-robin over findings (each finding's best chunk first, then second
    best...) so one finding with long sections cannot crowd out the others.
    """
    lists = [retrieved.get(fid, []) for fid in finding_ids]
    chosen: list[DocChunk] = []
    seen: set[str] = set()
    used = 0
    for rank in range(max((len(x) for x in lists), default=0)):
        for docs in lists:
            if rank >= len(docs):
                continue
            chunk = docs[rank].chunk
            if chunk.id in seen:
                continue
            if used + len(chunk.text) > budget_chars and chosen:
                continue
            seen.add(chunk.id)
            chosen.append(chunk)
            used += len(chunk.text)
    return chosen
