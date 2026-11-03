"""Okapi BM25, from scratch, with a code-aware tokenizer.

Why BM25 instead of embeddings: the corpus is one focused migration guide
(~100 sections) and queries are dominated by exact identifiers (`orm_mode`,
`root_validator`, `parse_obj`). Lexical matching on identifiers is precisely
what BM25 is good at; it needs no model, no vector store, and is deterministic.

score(q, d) = sum over query terms t of
    idf(t) * tf(t, d) * (k1 + 1) / (tf(t, d) + k1 * (1 - b + b * |d| / avgdl))
idf(t) = ln((N - df(t) + 0.5) / (df(t) + 0.5) + 1)      (always > 0)
"""

from __future__ import annotations

import math
import re
from collections import Counter
from collections.abc import Sequence

_WORD = re.compile(r"[A-Za-z_][A-Za-z0-9_]*|\d+")
_CAMEL = re.compile(r"[A-Z]+(?=[A-Z][a-z])|[A-Z]?[a-z]+|[A-Z]+|\d+")
STOPWORDS = frozenset(
    "a an and are as at be by can for from has have if in into is it its of on or "  # noqa: SIM905
    "that the their then there these this to was were will with you your not use used".split()
)


def tokenize(text: str) -> list[str]:
    """`orm_mode` -> orm_mode, orm, mode;  `BaseModel` -> basemodel, base, model.

    Keeping the whole identifier *and* its parts means an exact identifier
    match scores highest, while `model_validate` still relates to "validate".
    """
    tokens: list[str] = []
    for word in _WORD.findall(text):
        lower = word.lower()
        if lower in STOPWORDS:
            continue
        tokens.append(_singular(lower))
        parts = [p.lower() for piece in word.split("_") for p in _CAMEL.findall(piece)]
        if len(parts) > 1:
            tokens.extend(_singular(p) for p in parts if p not in STOPWORDS and p != lower)
    return tokens


def _singular(token: str) -> str:
    """Minimal plural folding ("integers" -> "integer") so prose and errors meet in the middle."""
    if len(token) > 4 and token.endswith("s") and not token.endswith(("ss", "us", "is")):
        return token[:-1]
    return token


class BM25:
    def __init__(self, documents: Sequence[str], k1: float = 1.5, b: float = 0.75) -> None:
        if not documents:
            raise ValueError("BM25 needs at least one document")
        self.k1 = k1
        self.b = b
        self.term_freqs = [Counter(tokenize(d)) for d in documents]
        self.lengths = [sum(tf.values()) for tf in self.term_freqs]
        self.avgdl = sum(self.lengths) / len(self.lengths) or 1.0
        df: Counter[str] = Counter()
        for tf in self.term_freqs:
            df.update(tf.keys())
        n = len(documents)
        self.idf = {t: math.log((n - f + 0.5) / (f + 0.5) + 1.0) for t, f in df.items()}

    def scores(self, query: str) -> list[float]:
        q = Counter(tokenize(query))
        out = []
        for tf, length in zip(self.term_freqs, self.lengths, strict=True):
            norm = self.k1 * (1 - self.b + self.b * length / self.avgdl)
            s = 0.0
            for term, qtf in q.items():
                f = tf.get(term)
                if f:
                    s += qtf * self.idf[term] * f * (self.k1 + 1) / (f + norm)
            out.append(s)
        return out

    def top(self, query: str, k: int) -> list[tuple[int, float]]:
        """(document index, score) of the k best matches with score > 0, best first."""
        ranked = sorted(enumerate(self.scores(query)), key=lambda p: (-p[1], p[0]))
        return [(i, s) for i, s in ranked[:k] if s > 0]
