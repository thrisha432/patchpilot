"""The migration loop with a scripted model and scripted validation results."""

from __future__ import annotations

import json

from patchpilot.llm.provider import LLMQuotaExhausted, ScriptedProvider
from patchpilot.migration.orchestrator import MigrationConfig, Orchestrator
from patchpilot.models import RunStatus, TestOutcome, ValidationResult
from patchpilot.reporting.report import to_json, to_markdown
from patchpilot.validation.runner import ScriptedValidator

MODELS = """
from pydantic import BaseModel
class User(BaseModel):
    name: str
    class Config:
        orm_mode = True
"""
SERVICE = """
from app.models import User
def load(d) -> User:
    return User.parse_obj(d)
"""


def answer(*edits: tuple[str, str], ids: list[str] | None = None) -> str:
    return json.dumps(
        {
            "edits": [
                {"finding_ids": ids or [], "search": s, "replace": r, "explanation": "because"}
                for s, r in edits
            ],
            "notes": "",
        }
    )


def failing(msg: str = "boom", nodeid: str = "tests/test_m.py::test_x") -> ValidationResult:
    return ValidationResult(
        stage="tests",
        passed=False,
        tests=[TestOutcome(nodeid=nodeid, outcome="failed", message=msg)],
    )


def passing(n: int = 2) -> ValidationResult:
    return ValidationResult(
        stage="tests",
        passed=True,
        tests=[TestOutcome(nodeid=f"t{i}", outcome="passed") for i in range(n)],
    )


CONFIG_FIX = answer(
    ("from pydantic import BaseModel", "from pydantic import BaseModel, ConfigDict"),
    (
        "    class Config:\n        orm_mode = True",
        "    model_config = ConfigDict(from_attributes=True)",
    ),
)
SERVICE_FIX = answer(("    return User.parse_obj(d)", "    return User.model_validate(d)"))


def repo_files():
    return {
        "app/__init__.py": "",
        "app/models.py": MODELS,
        "app/service.py": SERVICE,
        "tests/test_m.py": "def test_x(): pass\n",
    }


def test_success_first_try(make_repo, profile):
    repo = make_repo(repo_files())
    provider = ScriptedProvider([CONFIG_FIX, SERVICE_FIX])
    validator = ScriptedValidator([failing(), passing()])
    report = Orchestrator(profile, provider, validator).run(repo)
    assert (
        report.status is RunStatus.SUCCESS
        and report.kept_round == 0
        and report.repair_attempts == 0
    )
    assert report.changed_files == ["app/models.py", "app/service.py"]
    assert report.residual_findings == []
    assert "+    model_config = ConfigDict(from_attributes=True)" in report.diff
    assert (repo / "app/models.py").read_text().count("orm_mode") == 1  # original untouched
    # Every prompt carried the retrieved documentation and the repository context.
    assert all("Changes to config" in p or "BaseModel" in p for _, p in provider.calls)
    assert "Pydantic model classes in this repository: User" in provider.calls[0][1]
    states = [s.state for s in report.steps]
    assert states == [
        "ANALYZE",
        "WORKSPACE",
        "BASELINE",
        "DISCOVER",
        "RETRIEVE",
        "PATCH",
        "VALIDATE",
        "SELECT",
        "RESIDUAL",
    ]


def test_repair_receives_the_failure_and_fixes_it(make_repo, profile):
    repo = make_repo(repo_files())
    half_fix = answer(
        (
            "    class Config:\n        orm_mode = True",
            "    model_config = ConfigDict(from_attributes=True)",
        )
    )
    import_fix = answer(
        ("from pydantic import BaseModel", "from pydantic import BaseModel, ConfigDict")
    )
    provider = ScriptedProvider([half_fix, SERVICE_FIX, import_fix])
    error = "NameError: name 'ConfigDict' is not defined\napp/models.py:4: in User"
    validator = ScriptedValidator([failing(), failing(error), passing()])
    report = Orchestrator(profile, provider, validator).run(repo)
    assert (
        report.status is RunStatus.SUCCESS
        and report.repair_attempts == 1
        and report.kept_round == 1
    )
    repair_prompt = provider.calls[2][1]
    assert "FAILED validation" in repair_prompt and "NameError" in repair_prompt
    assert "model_config = ConfigDict" in repair_prompt  # repairs see the current (patched) content
    assert len(report.rounds[1].patches) == 1  # only the file named in the traceback was repaired


def test_keeps_best_state_when_repairs_make_things_worse(make_repo, profile):
    repo = make_repo(repo_files())
    breaks = answer(("    return User.model_validate(d)", "    return User.model_validate(d) +"))
    provider = ScriptedProvider([CONFIG_FIX, SERVICE_FIX, breaks, breaks])
    two_of_three = ValidationResult(
        stage="tests", passed=False,
        tests=[TestOutcome(nodeid="a", outcome="passed"), TestOutcome(nodeid="b", outcome="passed"), TestOutcome(nodeid="c", outcome="failed", message="app/service.py")],
    )  # fmt: skip
    validator = ScriptedValidator([failing(), two_of_three, failing("x"), failing("x")])
    report = Orchestrator(profile, provider, validator, MigrationConfig(max_repairs=1)).run(repo)
    assert report.status is RunStatus.PARTIAL and report.kept_round == 0
    assert report.final_validation is not None and report.final_validation.n_passed == 2
    assert "model_validate(d)\n" in report.diff and "model_validate(d) +" not in report.diff


def test_nothing_better_than_original_restores_it(make_repo, profile):
    repo = make_repo(repo_files())
    bad = answer(("this text is not in the file", "x"))
    validator = ScriptedValidator([passing(1), failing(), failing()])  # baseline: 1 passing
    report = Orchestrator(
        profile, ScriptedProvider([bad, bad, bad]), validator, MigrationConfig(max_repairs=1)
    ).run(repo)
    assert report.status is RunStatus.FAILED and report.kept_round is None and report.diff == ""
    rejected = report.rounds[0].patches[0].outcomes[0]
    assert not rejected.applied and "not found" in rejected.reason


def test_quota_exhaustion_stops_cleanly(make_repo, profile):
    repo = make_repo(repo_files())
    provider = ScriptedProvider([LLMQuotaExhausted("daily quota exhausted")])
    report = Orchestrator(profile, provider, ScriptedValidator([failing()])).run(repo)
    assert report.status is RunStatus.FAILED and "quota" in report.message and report.diff == ""


def test_nothing_to_do_and_unsupported(make_repo, profile):
    clean = make_repo({"app/m.py": "x = 1\n"})
    report = Orchestrator(profile, ScriptedProvider([]), ScriptedValidator([passing()])).run(clean)
    assert report.status is RunStatus.NOTHING_TO_DO
    empty = make_repo({"tests/test_x.py": "def test(): pass\n"})
    assert (
        Orchestrator(profile, ScriptedProvider([]), ScriptedValidator([])).run(empty).status
        is RunStatus.UNSUPPORTED
    )


def test_discovery_turns_unexplained_failure_into_a_target(make_repo, profile):
    repo = make_repo(
        {
            "app/__init__.py": "",
            "app/stock.py": "from pydantic import BaseModel\n\nclass S(BaseModel):\n    units: int\n\ndef make(r):\n    return S(units=r)\n",
            "tests/test_s.py": "def test(): pass\n",
        }
    )
    trace = "app/stock.py:7: in make\n    return S(units=r)\nE   ValidationError: Input should be a valid integer, got a number with a fractional part"
    provider = ScriptedProvider([answer(("    return S(units=r)", "    return S(units=int(r))"))])
    validator = ScriptedValidator([failing(trace), passing()])
    report = Orchestrator(profile, provider, validator).run(repo)
    assert report.status is RunStatus.SUCCESS
    [found] = report.discovered_findings
    assert (found.rule, found.file, found.line, found.end_line) == (
        "test-failure",
        "app/stock.py",
        6,
        7,
    )
    assert (
        "Type conversion from floats to integers" in provider.calls[0][1]
    )  # retrieved from the error text


def test_no_retrieval_ablation_sends_no_docs(make_repo, profile):
    repo = make_repo(repo_files())
    provider = ScriptedProvider([CONFIG_FIX, SERVICE_FIX])
    Orchestrator(
        profile,
        provider,
        ScriptedValidator([failing(), passing()]),
        MigrationConfig(retrieval=False),
    ).run(repo)
    assert all("(no documentation retrieved)" in p for _, p in provider.calls)


def test_unverified_when_repository_has_no_tests(make_repo, profile):
    repo = make_repo({"app/__init__.py": "", "app/models.py": MODELS})
    skipped = ValidationResult(stage="skipped", passed=True)
    report = Orchestrator(
        profile, ScriptedProvider([CONFIG_FIX]), ScriptedValidator([skipped, skipped])
    ).run(repo)
    assert report.status is RunStatus.UNVERIFIED


def test_apply_to_original_only_on_success(make_repo, profile):
    repo = make_repo(repo_files())
    cfg = MigrationConfig(apply_to_original=True)
    report = Orchestrator(
        profile,
        ScriptedProvider([CONFIG_FIX, SERVICE_FIX]),
        ScriptedValidator([failing(), passing()]),
        cfg,
    ).run(repo)
    assert report.applied_to_original and "model_validate" in (repo / "app/service.py").read_text()


def test_report_renders_everything(make_repo, profile):
    repo = make_repo(repo_files())
    report = Orchestrator(
        profile,
        ScriptedProvider([CONFIG_FIX, SERVICE_FIX]),
        ScriptedValidator([failing(), passing()]),
    ).run(repo)
    md = to_markdown(report)
    for expected in (
        "✅ Validation passed",
        "| Tests before | failed: 0 passed, 1 failed |",
        "```diff",
        "Docs:",
        "resolved",
    ):
        assert expected in md
    assert json.loads(to_json(report))["status"] == "success"


def test_score_prefers_importing_modules_over_fewer_failures():
    # Found on a real repository: fixing imports turned 15 collection errors into 26
    # individual failures, and the old ordering called that a regression.
    collection = [
        TestOutcome(nodeid=f"tests.test_{i}", outcome="error", message="collection failure\nE ...")
        for i in range(15)
    ]
    imported = [
        TestOutcome(nodeid=f"tests/test_{i}.py::test_{j}", outcome="failed")
        for i in range(13)
        for j in range(2)
    ]
    before = ValidationResult(stage="tests", passed=False, tests=collection)
    after = ValidationResult(stage="tests", passed=False, tests=imported)
    assert before.n_collection_errors == 15 and after.n_collection_errors == 0
    assert after.score() > before.score()
