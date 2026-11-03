from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from patchpilot.models import Confidence, Finding
from patchpilot.retrieval.bm25 import BM25, tokenize
from patchpilot.retrieval.chunker import MAX_CHUNK_CHARS, chunk_markdown, load_guides
from patchpilot.retrieval.retriever import Retriever, context_for_file


def test_tokenize_keeps_identifiers_and_parts():
    assert tokenize("orm_mode") == ["orm_mode", "orm", "mode"]
    assert tokenize("BaseModel.parse_obj") == [
        "basemodel",
        "base",
        "model",
        "parse_obj",
        "parse",
        "obj",
    ]
    assert tokenize("the integers") == ["integer"]  # stopword dropped, plural folded
    assert tokenize("class status") == ["class", "status"]  # "ss"/"us" endings untouched


def test_bm25_prefers_rare_exact_terms():
    docs = ["config config config", "orm_mode is renamed to from_attributes", "unrelated text"]
    bm = BM25(docs)
    assert bm.top("orm_mode", 3)[0][0] == 1
    assert bm.top("nothing matches here zzz", 3) == []


def test_bm25_rejects_empty_corpus():
    with pytest.raises(ValueError):
        BM25([])


@given(
    st.lists(st.text(alphabet="abc _", min_size=1, max_size=30), min_size=1, max_size=8),
    st.text(alphabet="abc _", max_size=20),
)
def test_bm25_scores_are_finite_and_nonnegative(docs, query):
    for score in BM25(docs).scores(query):
        assert score >= 0 and score == score  # not NaN


def test_chunker_ignores_hashes_in_code_fences():
    md = "# Guide\nintro\n## Config\ntext\n```python\n# not a heading\nx = 1\n```\nmore\n## Validators\nv\n"
    chunks = chunk_markdown(md, "g.md")
    assert [c.heading for c in chunks] == ["Guide", "Guide > Config", "Guide > Validators"]
    assert "# not a heading" in chunks[1].text and "more" in chunks[1].text
    assert chunks[1].id == "g.md#config"


def test_chunker_splits_long_sections_outside_fences():
    body = "\n".join(f"* item {i} " + "x" * 60 for i in range(80))
    chunks = chunk_markdown(f"# Long\n{body}\n", "g.md")
    assert len(chunks) > 1 and all(len(c.text) <= MAX_CHUNK_CHARS * 1.2 for c in chunks)
    assert len({c.id for c in chunks}) == len(chunks)


def _finding(rule: str, symbols: tuple[str, ...], message: str) -> Finding:
    return Finding(
        id=f"x.py:1:{rule}", rule=rule, title=rule, file="x.py", line=1, end_line=1,
        snippet="", message=message, confidence=Confidence.HIGH, symbols=symbols,
    )  # fmt: skip


# Labeled relevance on the real guide: the section a migration engineer would read.
CASES = [
    (("Config", "ConfigDict", "orm_mode"), "class Config is deprecated: use model_config", "Changes to config"),
    (("validator", "field_validator", "pre"), "@validator is deprecated", "`@validator` and `@root_validator` are deprecated"),
    (("root_validator", "model_validator"), "@root_validator is deprecated", "`@validator` and `@root_validator` are deprecated"),
    (("Optional", "required", "default"), "Optional field without a default is required", "Required, optional, and nullable fields"),
    (("BaseSettings",), "BaseSettings moved to pydantic-settings", "`BaseSettings` has moved to `pydantic-settings`"),
    (("parse_obj_as", "TypeAdapter"), "parse_obj_as is deprecated: use TypeAdapter", "Introduction of `TypeAdapter`"),
    (("GenericModel", "Generic", "generics"), "GenericModel was removed", "Changes to `pydantic.generics.GenericModel`"),
    (("Field", "regex", "pattern"), "Field(regex=...) -> pattern", "Changes to `pydantic.Field`"),
    (("dict", "model_dump"), ".dict() -> .model_dump()", "Changes to `pydantic.BaseModel`"),
    (("integer", "fractional"), "Input should be a valid integer, got a number with a fractional part", "Type conversion from floats to integers"),
]  # fmt: skip


@pytest.mark.parametrize(("symbols", "message", "expected"), CASES)
def test_retrieval_recall_at_3_on_the_real_guide(profile, symbols, message, expected):
    retriever = Retriever.from_directory(profile.guides_dir)
    hits = retriever.for_finding(_finding("r", symbols, message), k=3)
    assert expected in [h.chunk.heading.split(" > ")[-1] for h in hits]


def test_context_for_file_round_robin_dedup_and_budget(profile):
    chunks = load_guides(profile.guides_dir)
    retriever = Retriever(chunks)
    a = retriever.search("orm_mode from_attributes config", 3)
    b = retriever.search("root_validator model_validator", 3)
    ctx = context_for_file({"a": a, "b": b}, ["a", "b"], budget_chars=10_000)
    assert ctx[0] == a[0].chunk and ctx[1] == b[0].chunk  # each finding's best chunk first
    assert len({c.id for c in ctx}) == len(ctx)
    tiny = context_for_file({"a": a, "b": b}, ["a", "b"], budget_chars=1)
    assert len(tiny) == 1  # always at least one chunk, never more than the budget allows
