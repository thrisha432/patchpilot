"""Analyzer rules, including the precision cases that make auto-fixing safe."""

from __future__ import annotations

from patchpilot.analyzer.analyzer import analyze
from patchpilot.analyzer.scanner import is_test_path
from patchpilot.models import Confidence


def rules(report):
    return sorted((f.file, f.line, f.rule, f.confidence.value) for f in report.findings)


def test_config_class_and_renamed_keys(make_repo, profile):
    repo = make_repo(
        {
            "m.py": """
            from pydantic import BaseModel
            class User(BaseModel):
                name: str
                class Config:
                    orm_mode = True
                    allow_population_by_field_name = True
            """
        }
    )
    [f] = analyze(repo, profile).findings
    assert f.rule == "config-class" and (f.line, f.end_line) == (4, 6)
    assert "`orm_mode` -> `from_attributes`" in f.message
    assert "populate_by_name" in f.message
    assert "orm_mode" in f.symbols


def test_config_on_non_model_class_ignored(make_repo, profile):
    repo = make_repo({"m.py": "class Thing:\n    class Config:\n        orm_mode = True\n"})
    assert analyze(repo, profile).findings == []


def test_validators(make_repo, profile):
    repo = make_repo(
        {
            "m.py": """
            import pydantic as pd
            from pydantic import BaseModel, validator as v, root_validator
            class M(BaseModel):
                a: int
                @v("a", pre=True, always=True)
                def check(cls, value, values):
                    return value
                @root_validator(pre=True)
                def r(cls, values):
                    return values
                @pd.validator("a")
                def other(cls, value):
                    return value
            """
        }
    )
    found = {(f.rule, f.line): f for f in analyze(repo, profile).findings}
    first = found[("validator", 5)]
    assert "mode='before'" in first.message and "info.data" in first.message
    assert (first.line, first.end_line) == (5, 7)  # the whole decorated function is in scope
    assert "mode='before'" in found[("root-validator", 8)].message
    assert ("validator", 11) in found  # attribute-style pd.validator resolved through the alias


def test_unrelated_decorator_named_validator_ignored(make_repo, profile):
    repo = make_repo(
        {
            "m.py": """
            from mylib import validator
            from pydantic import BaseModel
            class M(BaseModel):
                @validator("a")
                def check(cls, v):
                    return v
            """
        }
    )
    assert [f.rule for f in analyze(repo, profile).findings] == []


def test_method_receiver_inference(make_repo, profile):
    repo = make_repo(
        {
            "app/models.py": """
            from typing import List, Optional
            from pydantic import BaseModel
            class Address(BaseModel):
                city: str
            class User(BaseModel):
                name: str
                address: Optional[Address] = None
            """,
            "app/admin.py": """
            from app.models import User
            class Admin(User):
                level: int = 1
            """,
            "app/service.py": """
            from typing import List
            from app.models import User
            from app.admin import Admin

            class Response:
                def json(self): return {}

            def load(data) -> User:
                return User.parse_obj(data)

            def handle(raw, resp: Response, admin: Admin, users: List[User]):
                u = User.from_orm(raw)          # 12 classmethod on model
                a = u.json()                    # 13 assigned from a model-returning call
                b = resp.json()                 # 14 annotated with a non-model class: skipped
                c = {"k": 1}.copy()             # 15 literal: skipped
                d = admin.copy()                # 16 subclass defined in another file
                e = load(raw).dict()            # 17 function return annotation
                f = u.address.json()            # 18 field annotation on the owner model
                g = [x.dict() for x in users]   # 19 comprehension over List[User]
                h = mystery.dict()              # 20 unknown receiver: LOW, never auto-fixed
                i = mystery.parse_raw("{}")     # 21 pydantic-only method name: MEDIUM
                return a, b, c, d, e, f, g, h, i
            """,
        }
    )
    report = analyze(repo, profile)
    assert report.model_classes == ["Address", "Admin", "User"]
    got = {f.line: f.confidence for f in report.findings if f.file == "app/service.py"}
    assert got == {
        9: Confidence.HIGH,
        12: Confidence.HIGH,
        13: Confidence.HIGH,
        16: Confidence.HIGH,
        17: Confidence.HIGH,
        18: Confidence.HIGH,
        19: Confidence.HIGH,
        20: Confidence.LOW,
        21: Confidence.MEDIUM,
    }
    assert all(f.line != 20 for f in report.actionable())


def test_optional_without_default_and_custom_root(make_repo, profile):
    repo = make_repo(
        {
            "m.py": """
            from typing import List, Optional, Union
            from pydantic import BaseModel
            class P(BaseModel):
                a: Optional[int]
                b: Optional[int] = None
                c: int | None
                d: Union[str, None]
                e: str
            class L(BaseModel):
                __root__: List[int]
            """
        }
    )
    got = rules(analyze(repo, profile))
    assert [(line, rule) for _, line, rule, _ in got] == [
        (4, "optional-no-default"),
        (6, "optional-no-default"),
        (7, "optional-no-default"),
        (10, "custom-root"),
    ]


def test_field_kwargs_imports_and_dunders(make_repo, profile):
    repo = make_repo(
        {
            "m.py": """
            from pydantic import BaseModel, BaseSettings, Field, constr, parse_obj_as, validate_arguments
            from pydantic.generics import GenericModel
            Sku = constr(regex="x")
            class P(BaseModel):
                a: str = Field(..., regex="^a$", min_items=1, description="ok")
            @validate_arguments
            def f(x: int): return x
            items = parse_obj_as(list, [])
            names = P.__fields__
            """
        }
    )
    got = [(line, rule) for _, line, rule, _ in rules(analyze(repo, profile))]
    assert got == [
        (1, "moved-import"),  # BaseSettings
        (1, "moved-import"),  # parse_obj_as
        (1, "moved-import"),  # validate_arguments
        (2, "moved-import"),  # pydantic.generics
        (3, "field-kwargs"),
        (5, "field-kwargs"),  # regex
        (5, "field-kwargs"),  # min_items (description is fine)
        (6, "moved-import"),  # the decorator usage
        (8, "parse-obj-as"),
        (9, "deprecated-method"),
    ]
    ids = [f.id for f in analyze(repo, profile).findings]
    assert len(ids) == len(set(ids))  # duplicates on one line get distinct ids


def test_generic_model_subclass(make_repo, profile):
    repo = make_repo(
        {
            "m.py": """
            from typing import Generic, TypeVar
            from pydantic.generics import GenericModel
            T = TypeVar("T")
            class Page(GenericModel, Generic[T]):
                items: list
            def load(raw):
                return Page[int].parse_obj(raw)
            """
        }
    )
    report = analyze(repo, profile)
    assert "Page" in report.model_classes
    assert {f.rule for f in report.findings} == {
        "moved-import",
        "generic-model",
        "deprecated-method",
    }
    [method] = [f for f in report.findings if f.rule == "deprecated-method"]
    assert method.confidence is Confidence.HIGH  # Page[int] resolves to the Page model


def test_test_files_are_context_but_never_targets(make_repo, profile):
    repo = make_repo(
        {
            "app/m.py": "from pydantic import BaseModel\nclass U(BaseModel):\n    a: int\n",
            "tests/test_m.py": "from app.m import U\ndef test(): U(a=1).dict()\n",
            "conftest.py": "x = 1\n",
        }
    )
    report = analyze(repo, profile)
    assert report.findings == []
    assert {f.path for f in report.files if f.is_test} == {"tests/test_m.py", "conftest.py"}


def test_scanner_skips_venvs_and_marks_parse_errors(make_repo, profile):
    repo = make_repo(
        {
            "ok.py": "x = 1\n",
            "broken.py": "def f(:\n",
            ".venv/lib/site.py": "from pydantic import BaseModel\n",
            "pkg.egg-info/x.py": "x = 1\n",
        }
    )
    report = analyze(repo, profile)
    assert {f.path: f.parse_error for f in report.files} == {"broken.py": True, "ok.py": False}


def test_is_test_path():
    assert is_test_path("tests/unit/helpers.py")
    assert (
        is_test_path("pkg/test_x.py")
        and is_test_path("pkg/x_test.py")
        and is_test_path("conftest.py")
    )
    assert not is_test_path("pkg/testing_utils.py") and not is_test_path("contest.py")


def test_gaps_found_by_the_tier2_benchmark(make_repo, profile):
    """Each case was missed by v0.1 and exposed by a tier-2 benchmark task."""
    repo = make_repo(
        {
            "app/legacy.py": """
            class Snapshot:
                @classmethod
                def parse_obj(cls, data):
                    return cls()
            """,
            "app/m.py": """
            from typing import Generic, List, TypeVar
            from pydantic import BaseModel, validator
            from pydantic.generics import GenericModel
            from app.legacy import Snapshot
            T = TypeVar("T")
            def norm(v):
                return v
            class Page(GenericModel, Generic[T]):
                items: List[T]
            class C(BaseModel):
                a: str
                _norm_a = validator("a", allow_reuse=True)(norm)
            def page_of() -> Page[C]:
                return Page[C](items=[])
            def refs(rows, c: C):
                parsed = list(map(C.parse_obj, rows))
                handler = c.json
                body = page_of().json()
                snap = Snapshot.parse_obj({})
                return parsed, handler, body, snap
            """,
        }
    )
    report = analyze(repo, profile)
    got = {(f.line, f.rule, f.confidence.value) for f in report.findings if f.file == "app/m.py"}
    assert (12, "validator", "high") in got  # validator(...)(fn), no decorator (task 30)
    assert (16, "deprecated-method", "high") in got  # map(C.parse_obj, rows) (task 31)
    assert (17, "deprecated-method", "high") in got  # handler = c.json (task 31)
    assert (18, "deprecated-method", "high") in got  # Page[C] return annotation (task 32)
    assert not any(line == 19 for line, _, _ in got)  # Snapshot is not a model (task 25)


def test_analyzer_survives_code_that_crashed_tree_sitter_0_26(tmp_path):
    """tree-sitter 0.26.0 segfaulted inside the analyzer on this real-world file
    (found by the real-repository evaluation). Run in a subprocess so a crash fails
    this test instead of killing pytest. tree-sitter is pinned below 0.26."""
    import subprocess
    import sys
    from pathlib import Path

    src = Path(__file__).parents[1] / "fixtures" / "ts026_crash_case.py.txt"
    target = tmp_path / "pkg" / "case.py"
    target.parent.mkdir()
    target.write_bytes(src.read_bytes())
    code = (
        "import sys; from pathlib import Path; "
        "from patchpilot.analyzer.analyzer import analyze; from patchpilot.profiles import get_profile; "
        "print(len(analyze(Path(sys.argv[1]), get_profile('pydantic-v2')).findings))"
    )
    proc = subprocess.run(
        [sys.executable, "-I", "-c", code, str(target.parent)], capture_output=True, text=True
    )
    assert proc.returncode == 0, f"analyzer crashed (exit {proc.returncode}): {proc.stderr[-500:]}"


def test_self_referencing_assignment_does_not_recurse(make_repo, profile):
    # Found on Prefect 2.10: `flow = flow.copy(...)` sent receiver inference into a loop.
    repo = make_repo(
        {
            "app/flows.py": (
                "from pydantic import BaseModel\n\n"
                "class Flow(BaseModel):\n    name: str\n\n"
                "def rename(flow: Flow, other):\n"
                "    flow = flow.copy(update={'name': 'x'})\n"
                "    other = other.copy()\n"
                "    other = other.copy()\n"
                "    return flow.dict(), other.dict()\n"
            )
        }
    )
    report = analyze(repo, profile)
    found = {(f.rule, f.line, f.confidence) for f in report.findings}
    assert ("deprecated-method", 7, Confidence.HIGH) in found  # flow.copy: parameter is a Flow
    assert ("deprecated-method", 8, Confidence.LOW) in found  # other: type unknown
    assert not any(f.rule == "analysis-error" for f in report.findings)


def test_one_failing_file_does_not_sink_the_analysis(make_repo, profile, monkeypatch):
    from patchpilot.profiles.pydantic_v2 import detector

    repo = make_repo(
        {
            "app/a.py": "from pydantic import BaseModel\n\nclass A(BaseModel):\n    x: int\n\nA(x=1).dict()\n",
            "app/b.py": "from pydantic import BaseModel\n\nclass B(BaseModel):\n    y: int\n",
        }
    )
    real_run = detector._Detector.run

    def run(self):
        if self.pf.path == "app/b.py":
            raise RecursionError("boom")
        return real_run(self)

    monkeypatch.setattr(detector._Detector, "run", run)
    report = analyze(repo, profile)
    errors = [f for f in report.findings if f.rule == "analysis-error"]
    assert [(f.file, f.confidence) for f in errors] == [("app/b.py", Confidence.LOW)]
    assert any(f.file == "app/a.py" and f.rule != "analysis-error" for f in report.findings)
    assert "app/b.py" not in report.files_to_migrate()  # LOW: reported, never auto-fixed


def test_same_class_name_in_two_modules_is_resolved_through_imports(make_repo, profile):
    # Found on Netflix Dispatch: `Service` is a Pydantic model in one module and a
    # SQLAlchemy table in another. Matching by bare name flagged the table's `.dict()`.
    repo = make_repo(
        {
            "app/__init__.py": "",
            "app/schemas.py": "from pydantic import BaseModel\n\nclass Service(BaseModel):\n    name: str\n",
            "app/tables.py": "class Base:\n    def dict(self):\n        return {}\n\nclass Service(Base):\n    pass\n",
            "app/crud.py": (
                "from .tables import Service\n"
                "from app.schemas import Service as ServiceIn\n\n"
                "def update(service: Service, service_in: ServiceIn):\n"
                "    a = service.dict()\n"
                "    b = service_in.dict()\n"
                "    return a, b\n"
            ),
        }
    )
    hits = {
        f.line: f.confidence for f in analyze(repo, profile).findings if f.file == "app/crud.py"
    }
    assert hits.get(6) is Confidence.HIGH  # the model, imported under an alias
    assert hits.get(5) is not Confidence.HIGH  # the SQLAlchemy table's own dict()


def test_base_class_from_an_installed_package_is_not_a_repo_model(make_repo, profile):
    # Found on Prefect: `class DateTimeTZ(pendulum.DateTime)` was taken for a model
    # because Prefect also defines a Pydantic `class DateTime(Block)`.
    repo = make_repo(
        {
            "blocks.py": "from pydantic import BaseModel\n\nclass DateTime(BaseModel):\n    value: str\n",
            "fields.py": (
                "import pendulum\n\n"
                "class DateTimeTZ(pendulum.DateTime):\n"
                "    @classmethod\n"
                "    def __get_validators__(cls):\n"
                "        yield cls.validate\n"
            ),
        }
    )
    report = analyze(repo, profile)
    assert "DateTimeTZ" not in report.model_classes
    assert not [f for f in report.actionable() if f.file == "fields.py"]


def test_call_to_a_custom_override_is_reported_not_auto_fixed(make_repo, profile):
    # Found on Prefect: PrefectBaseModel.dict(json_compatible=...) overrides BaseModel.dict.
    # Renaming calls to `.model_dump(json_compatible=True)` would raise TypeError.
    repo = make_repo(
        {
            "base.py": (
                "from pydantic import BaseModel\n\n"
                "class AppModel(BaseModel):\n"
                "    def dict(self, *, json_compatible=False, **kw):\n"
                "        return super().dict(**kw)\n"
            ),
            "flows.py": (
                "from base import AppModel\n\n"
                "class Flow(AppModel):\n    name: str\n\n"
                "def send(flow: Flow):\n"
                "    a = flow.dict(json_compatible=True)\n"
                "    b = flow.json()\n"
                "    return a, b\n"
            ),
        }
    )
    hits = {f.line: f for f in analyze(repo, profile).findings if f.file == "flows.py"}
    assert hits[7].confidence is Confidence.LOW and "base.py:4" in hits[7].message
    assert hits[8].confidence is Confidence.HIGH  # .json() is not overridden


def test_pydantic_fields_imports_that_still_exist_are_not_flagged(make_repo, profile):
    repo = make_repo(
        {
            "ok.py": "from pydantic.fields import Field, FieldInfo, PrivateAttr\n",
            "gone.py": "from pydantic.fields import FieldInfo, ModelField, SHAPE_SINGLETON\n",
        }
    )
    findings = analyze(repo, profile).findings
    assert not [f for f in findings if f.file == "ok.py"]
    [f] = [f for f in findings if f.file == "gone.py"]
    assert "ModelField, SHAPE_SINGLETON" in f.message and "FieldInfo," not in f.message


def test_override_found_through_a_module_path_receiver(make_repo, profile):
    # Prefect: `schemas.responses.FlowRunResponse.from_orm(model)` with a custom from_orm.
    repo = make_repo(
        {
            "schemas/__init__.py": "",
            "schemas/responses.py": (
                "from pydantic import BaseModel\n\n"
                "class FlowRunResponse(BaseModel):\n"
                "    name: str\n\n"
                "    @classmethod\n"
                "    def from_orm(cls, orm_flow_run):\n"
                "        return cls(name=orm_flow_run.name)\n"
            ),
            "api.py": "import schemas\n\ndef read(model):\n    return schemas.responses.FlowRunResponse.from_orm(model)\n",
        }
    )
    [f] = [f for f in analyze(repo, profile).findings if f.file == "api.py"]
    assert f.confidence is Confidence.LOW and "schemas/responses.py:7" in f.message


def test_override_on_a_class_with_a_dynamic_base(make_repo, profile):
    # Prefect: `class WorkQueueResponse(schemas.core.WorkQueue.subclass())` defines from_orm.
    repo = make_repo(
        {
            "responses.py": (
                "from pydantic import BaseModel\n\n"
                "class WorkQueue(BaseModel):\n"
                "    name: str\n\n"
                "class WorkQueueResponse(WorkQueue.subclass()):\n"
                "    @classmethod\n"
                "    def from_orm(cls, orm_work_queue):\n"
                "        return cls(name=orm_work_queue.name)\n"
            ),
            "api.py": "import responses\n\ndef read(wq):\n    return responses.WorkQueueResponse.from_orm(wq)\n",
        }
    )
    [f] = [f for f in analyze(repo, profile).findings if f.file == "api.py"]
    assert f.confidence is Confidence.LOW
