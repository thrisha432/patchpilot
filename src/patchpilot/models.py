"""Domain objects shared by every stage of the pipeline.

They are Pydantic models so that a whole run (findings, retrieved docs, edits,
validation results) serializes to one JSON report without extra glue.
"""

from __future__ import annotations

from enum import StrEnum
from typing import ClassVar

from pydantic import BaseModel, ConfigDict, Field


class Confidence(StrEnum):
    """How sure the analyzer is that a finding really is migration-sensitive.

    HIGH and MEDIUM findings are sent to the LLM. LOW findings (for example
    ``x.dict()`` where nothing says ``x`` is a Pydantic model) are reported for
    human review only, because "fixing" them would break non-Pydantic code.
    """

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class Finding(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str  # stable within one analysis, e.g. "models.py:12:config-class"
    rule: str
    title: str
    file: str  # repository-relative POSIX path
    line: int  # 1-based
    end_line: int  # 1-based, inclusive: the enclosing construct the fix may touch
    snippet: str
    message: str
    confidence: Confidence
    symbols: tuple[str, ...] = ()  # identifiers that drive retrieval, e.g. ("orm_mode",)


class FileInfo(BaseModel):
    path: str
    lines: int
    is_test: bool
    parse_error: bool = False


class AnalysisReport(BaseModel):
    root: str
    files: list[FileInfo]
    findings: list[Finding]
    model_classes: list[str]  # Pydantic model classes found, incl. transitive subclasses
    skipped: list[str] = Field(default_factory=list)  # paths skipped and why

    def actionable(self) -> list[Finding]:
        return [f for f in self.findings if f.confidence is not Confidence.LOW]

    def files_to_migrate(self) -> list[str]:
        return sorted({f.file for f in self.actionable()})


class DocChunk(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str  # e.g. "migration.md#changes-to-config"
    source: str
    heading: str  # full heading path, "Migration guide > Changes to config"
    text: str


class RetrievedDoc(BaseModel):
    chunk: DocChunk
    score: float


class Edit(BaseModel):
    """One search/replace edit proposed by the LLM for a single file."""

    search: str
    replace: str
    explanation: str = ""
    finding_ids: list[str] = Field(default_factory=list)


class EditOutcome(BaseModel):
    edit: Edit
    applied: bool
    reason: str = ""  # why it was rejected, or "fuzzy-whitespace" when matched loosely
    start_line: int | None = None


class FilePatchResult(BaseModel):
    file: str
    outcomes: list[EditOutcome]
    llm_notes: str = ""
    error: str = ""  # LLM/transport/parse failure for this file

    @property
    def applied(self) -> int:
        return sum(o.applied for o in self.outcomes)

    @property
    def rejected(self) -> int:
        return sum(not o.applied for o in self.outcomes)


class TestOutcome(BaseModel):
    __test__: ClassVar[bool] = False  # tell pytest this is not a test class

    nodeid: str
    outcome: str  # passed | failed | error | skipped
    message: str = ""


class ValidationResult(BaseModel):
    stage: str  # "syntax" | "tests" | "skipped"
    passed: bool
    syntax_errors: list[str] = Field(default_factory=list)
    tests: list[TestOutcome] = Field(default_factory=list)
    output_tail: str = ""
    duration_s: float = 0.0
    timed_out: bool = False

    @property
    def n_passed(self) -> int:
        return sum(t.outcome == "passed" for t in self.tests)

    @property
    def n_failed(self) -> int:
        return sum(t.outcome in ("failed", "error") for t in self.tests)

    def score(self) -> tuple[int, int, int]:
        """Ordering for "best state so far": parses > more tests passing > fewer failing."""
        return (int(not self.syntax_errors), self.n_passed, -self.n_failed)


class LLMUsage(BaseModel):
    calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    seconds: float = 0.0
    errors: int = 0
    # Equivalent API cost at list price, as reported by the provider. Informational:
    # the Gemini free tier and a Claude subscription are not billed per call.
    cost_usd: float = 0.0

    def add(self, other: LLMUsage) -> None:
        self.calls += other.calls
        self.prompt_tokens += other.prompt_tokens
        self.completion_tokens += other.completion_tokens
        self.seconds += other.seconds
        self.errors += other.errors
        self.cost_usd += other.cost_usd


class RunStatus(StrEnum):
    SUCCESS = "success"  # validation passed
    PARTIAL = "partial"  # patches applied, validation still failing; best state kept
    FAILED = "failed"  # nothing better than the original could be produced
    NOTHING_TO_DO = "nothing_to_do"
    UNVERIFIED = "unverified"  # applied, but the repository has no tests to run
    UNSUPPORTED = "unsupported"  # e.g. no Python files


class StepRecord(BaseModel):
    state: str
    seconds: float
    detail: str = ""


class Round(BaseModel):
    """One patch round: the initial patch (round 0) or a repair attempt (1, 2, ...)."""

    index: int
    patches: list[FilePatchResult]
    validation: ValidationResult
    commit: str = ""


class RunReport(BaseModel):
    repo: str
    profile: str
    model: str
    status: RunStatus
    analysis: AnalysisReport
    discovered_findings: list[Finding] = Field(default_factory=list)  # from failing baseline tests
    retrieved: dict[str, list[RetrievedDoc]] = Field(default_factory=dict)  # finding id -> docs
    baseline_validation: ValidationResult | None = None
    rounds: list[Round] = Field(default_factory=list)
    kept_round: int | None = None  # which round's state the workspace ends in
    residual_findings: list[Finding] = Field(default_factory=list)
    changed_files: list[str] = Field(default_factory=list)
    diff: str = ""
    workspace: str = ""
    usage: LLMUsage = Field(default_factory=LLMUsage)
    steps: list[StepRecord] = Field(default_factory=list)
    seconds: float = 0.0
    applied_to_original: bool = False
    message: str = ""

    @property
    def repair_attempts(self) -> int:
        return max(0, len(self.rounds) - 1)

    @property
    def final_validation(self) -> ValidationResult | None:
        if self.kept_round is None:
            return self.baseline_validation
        return self.rounds[self.kept_round].validation
