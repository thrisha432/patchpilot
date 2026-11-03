"""Test-guided repair scope and discovery coverage."""

from __future__ import annotations

from patchpilot.analyzer.analyzer import analyze
from patchpilot.migration.discovery import discover
from patchpilot.migration.edits import LineRange
from patchpilot.migration.scope_hints import repair_ranges
from patchpilot.models import TestOutcome, ValidationResult

API = """from pydantic import BaseModel

MESSAGE_CODES = {"field required": "MISSING"}
UNUSED = 1


def helper():
    return 2


def error_codes(payload):
    return {k: MESSAGE_CODES.get(k) for k in payload}
"""


def failed(nodeid: str, message: str) -> ValidationResult:
    return ValidationResult(
        stage="tests",
        passed=False,
        tests=[TestOutcome(nodeid=nodeid, outcome="failed", message=message)],
    )


def test_repair_ranges_cover_tested_functions_and_what_they_read(make_repo):
    repo = make_repo(
        {
            "app/api.py": API,
            "tests/test_api.py": "from app.api import error_codes\ndef test(): pass\n",
        }
    )
    v = failed("tests.test_api::test", "E   AssertionError: assert {} == {'a': 'MISSING'}")
    ranges = repair_ranges(repo, v, "app/api.py", API)
    assert LineRange(11, 12) in ranges  # error_codes itself
    assert LineRange(3, 3) in ranges  # MESSAGE_CODES, read by error_codes
    assert all(r.start not in (4, 7) for r in ranges)  # UNUSED and helper stay out of scope


def test_repair_ranges_include_traceback_lines(make_repo):
    repo = make_repo({"app/api.py": API, "tests/test_x.py": "def test(): pass\n"})
    v = failed("tests.test_x::test", "app/api.py:12: in error_codes\nE   KeyError")
    assert repair_ranges(repo, v, "app/api.py", API) == [LineRange(12, 12)]
    assert (
        repair_ranges(repo, ValidationResult(stage="tests", passed=True), "app/api.py", API) == []
    )


def test_discovery_skips_class_headers_already_explained(make_repo, profile):
    src = "from pydantic import BaseModel\n\n\nclass U(BaseModel):\n    a: int\n\n    class Config:\n        orm_mode = True\n"
    repo = make_repo({"app/m.py": src, "tests/test_m.py": "def test(): pass\n"})
    analysis = analyze(repo, profile)
    trace = "app/m.py:4: in <module>\n    class U(BaseModel):\nE   PydanticDeprecatedSince20: Support for class-based `config` is deprecated"
    assert discover(failed("tests.test_m", trace), analysis, repo) == []


def test_discovery_picks_up_deprecations_the_analyzer_missed(make_repo, profile):
    src = "from pydantic import BaseModel\n\n\nclass E(BaseModel):\n    a: int\n\n\ndef parse(rows, fn=None):\n    return [getattr(E, 'parse_obj')(r) for r in rows]\n"
    repo = make_repo({"app/m.py": src, "tests/test_m.py": "def test(): pass\n"})
    trace = "app/m.py:9: in parse\nE   pydantic.warnings.PydanticDeprecatedSince20: The `parse_obj` method is deprecated"
    [found] = discover(failed("tests.test_m::test", trace), analyze(repo, profile), repo)
    assert (found.file, found.line, found.end_line, found.rule) == (
        "app/m.py",
        8,
        9,
        "test-failure",
    )
