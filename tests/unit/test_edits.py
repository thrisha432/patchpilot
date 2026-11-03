"""Search/replace application: exact, tolerant, and refused edits."""

from __future__ import annotations

from hypothesis import given
from hypothesis import strategies as st

from patchpilot.migration.edits import LineRange, apply_edit, import_block_end, map_range, scope_for
from patchpilot.models import Edit

SRC = """from pydantic import BaseModel


class User(BaseModel):
    name: str

    class Config:
        orm_mode = True


def load(d):
    return User.parse_obj(d)
"""


def edit(search: str, replace: str) -> Edit:
    return Edit(search=search, replace=replace, explanation="t")


def test_exact_edit():
    new, out = apply_edit(
        SRC,
        edit(
            "    class Config:\n        orm_mode = True\n",
            "    model_config = ConfigDict(from_attributes=True)\n",
        ),
        None,
    )
    assert out.applied and out.reason == "" and out.start_line == 7
    assert "model_config = ConfigDict(from_attributes=True)\n\n\ndef load" in new


def test_trailing_whitespace_tolerated_and_recorded():
    new, out = apply_edit(
        SRC, edit("    class Config:   \n        orm_mode = True   ", "    model_config = {}"), None
    )
    assert out.applied and out.reason == "fuzzy-whitespace"
    assert "    model_config = {}\n" in new


def test_indent_shift_is_reapplied_to_replacement():
    # The model dropped the class-body indentation from both search and replace.
    new, out = apply_edit(
        SRC,
        edit(
            "class Config:\n    orm_mode = True",
            "model_config = ConfigDict(\n    from_attributes=True,\n)",
        ),
        None,
    )
    assert out.applied and out.reason == "fuzzy-indent:4"
    assert "    model_config = ConfigDict(\n        from_attributes=True,\n    )\n" in new


def test_not_found_ambiguous_empty_noop():
    for e, reason in [
        (edit("class Settings:", "x"), "not found"),
        (edit("\n\n", "x"), "empty search"),
        (edit("    name: str", "    name: str"), "no-op"),
    ]:
        new, out = apply_edit(SRC, e, None)
        assert not out.applied and reason in out.reason and new == SRC
    dup = SRC + "\nx = User.parse_obj({})\n"
    _, out = apply_edit(dup, edit("User.parse_obj(", "User.model_validate("), None)
    assert not out.applied and out.reason.startswith("ambiguous")


def test_scope_rejects_edits_far_from_findings():
    scope = [LineRange(7, 8)]
    _, out = apply_edit(
        SRC, edit("    return User.parse_obj(d)", "    return User.model_validate(d)"), scope
    )
    assert not out.applied and out.reason.startswith("out of scope")
    _, ok = apply_edit(SRC, edit("    class Config:", "    class Conf:"), scope)
    assert ok.applied


def test_whole_file_rewrites_rejected():
    big = "\n".join(f"x{i} = {i}" for i in range(40)) + "\n"
    _, out = apply_edit(big, edit(big, "y = 1\n"), None)
    assert not out.applied and out.reason.startswith("too large")


def test_import_block_end():
    assert import_block_end(SRC) == 1
    src = '"""Doc."""\n# c\nimport os\nfrom typing import (\n    List,\n)\n\nx = 1\n'
    assert import_block_end(src) == 6
    assert import_block_end("x = 1\nimport os\n") == 0


def test_map_range_follows_inserted_lines():
    original = "a\nb\nc\nd\n"
    current = "a\nNEW\nNEW2\nb\nc\nd\n"
    assert map_range(original, current, LineRange(3, 4)) == LineRange(5, 6)
    replaced = "a\nX\nY\nZ\nd\n"  # lines b, c replaced by three lines
    assert map_range(original, replaced, LineRange(2, 3)) == LineRange(2, 4)


def test_scope_for_includes_imports_and_margin():
    scope = scope_for(SRC, SRC, [LineRange(7, 8)])
    assert LineRange(5, 10) in scope and LineRange(1, 2) in scope


@given(
    st.lists(
        st.sampled_from(["a = 1", "b = 2", "    c = 3", "", "def f():"]), min_size=1, max_size=12
    ),
    st.data(),
)
def test_exact_single_match_always_applies_and_only_changes_that_region(lines, data):
    content = "\n".join(lines) + "\nUNIQUE_MARKER = 0\n"
    new, out = apply_edit(content, edit("UNIQUE_MARKER = 0", "UNIQUE_MARKER = 1"), None)
    assert out.applied and new == content.replace("UNIQUE_MARKER = 0", "UNIQUE_MARKER = 1")
