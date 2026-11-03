"""The migration workflow as an explicit state machine.

    ANALYZE -> RETRIEVE -> WORKSPACE -> BASELINE -> PATCH -> VALIDATE
        -> (REPAIR -> VALIDATE) x at most `max_repairs`
        -> SELECT (keep the best state seen) -> RESIDUAL -> REPORT

A plain loop with named states, not an agent framework: every transition is
visible in code and recorded (with timings) in the run report. The LLM never
chooses what runs next; it only proposes edits for one file at a time.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from patchpilot.analyzer.analyzer import analyze
from patchpilot.llm.patch_generator import request_edits
from patchpilot.llm.prompts import patch_prompt, repair_prompt
from patchpilot.llm.provider import LLMProvider, LLMQuotaExhausted
from patchpilot.migration.discovery import discover
from patchpilot.migration.edits import LineRange, apply_edit, map_range, scope_for
from patchpilot.migration.scope_hints import repair_ranges
from patchpilot.migration.workspace import Workspace
from patchpilot.models import (
    EditOutcome,
    FilePatchResult,
    Finding,
    LLMUsage,
    Round,
    RunReport,
    RunStatus,
    StepRecord,
    ValidationResult,
)
from patchpilot.profiles.base import Profile
from patchpilot.retrieval.retriever import Retriever, context_for_file
from patchpilot.validation.runner import Validator

MAX_FAILURE_CHARS = 3500


@dataclass
class MigrationConfig:
    retrieval: bool = True
    discover: bool = True  # turn unexplained baseline test failures into findings
    max_repairs: int = 2
    top_k: int = 3
    doc_budget_chars: int = 7000
    keep_workspace: bool = True
    apply_to_original: bool = False


@dataclass
class _State:
    report: RunReport
    workspace: Workspace | None = None
    originals: dict[str, str] = field(default_factory=dict)  # file -> original content
    best: tuple[tuple[int, ...], int | None, str] | None = None  # (score, round, commit)


class Orchestrator:
    def __init__(
        self,
        profile: Profile,
        provider: LLMProvider,
        validator: Validator,
        config: MigrationConfig | None = None,
        on_step: Callable[[str, str], None] | None = None,
    ) -> None:
        self.profile = profile
        self.provider = provider
        self.validator = validator
        self.config = config or MigrationConfig()
        self.retriever = (
            Retriever.from_directory(profile.guides_dir) if self.config.retrieval else None
        )
        self._on_step = on_step or (lambda state, detail: None)

    # -- public ------------------------------------------------------------------------

    def run(self, repo: Path) -> RunReport:
        started = time.monotonic()
        analysis = analyze(repo, self.profile)
        report = RunReport(
            repo=str(repo.resolve()),
            profile=self.profile.name,
            model=self.provider.name,
            status=RunStatus.FAILED,
            analysis=analysis,
        )
        st = _State(report)
        self._record(
            st,
            "ANALYZE",
            started,
            f"{len(analysis.files)} files, {len(analysis.findings)} findings",
        )
        try:
            self._run(st)
        except LLMQuotaExhausted as exc:
            report.status = RunStatus.FAILED
            report.message = str(exc)
            self._finish(st)
        report.seconds = round(time.monotonic() - started, 3)
        return report

    # -- states --------------------------------------------------------------------------

    def _record(self, st: _State, state: str, t0: float, detail: str = "") -> None:
        st.report.steps.append(
            StepRecord(state=state, seconds=round(time.monotonic() - t0, 3), detail=detail)
        )
        self._on_step(state, detail)

    def _run(self, st: _State) -> None:
        report = st.report
        a = report.analysis
        if not any(not f.is_test for f in a.files):
            report.status = RunStatus.UNSUPPORTED
            report.message = "No (non-test) Python files found."
            return
        t0 = time.monotonic()
        st.workspace = Workspace.create(Path(report.repo))
        report.workspace = str(st.workspace.root)
        self._record(st, "WORKSPACE", t0, report.workspace)

        # The repository's own tests on the target version, before any change.
        t0 = time.monotonic()
        baseline = report.baseline_validation = self.validator.validate(st.workspace.root)
        st.best = (baseline.score(), None, st.workspace.baseline)
        self._record(st, "BASELINE", t0, _summary(baseline))

        if self.config.discover and not baseline.passed:
            t0 = time.monotonic()
            report.discovered_findings = discover(baseline, a, st.workspace.root)
            self._record(
                st,
                "DISCOVER",
                t0,
                f"{len(report.discovered_findings)} failure locations not explained by static rules",
            )
        findings = [*a.actionable(), *report.discovered_findings]
        if not findings:
            report.status = RunStatus.NOTHING_TO_DO if baseline.passed else RunStatus.FAILED
            report.message = (
                "No migration-sensitive code found."
                if baseline.passed
                else "Tests fail on the target version, but no cause could be located."
            )
            report.kept_round = None
            return

        t0 = time.monotonic()
        if self.retriever is not None:
            report.retrieved = {
                f.id: self.retriever.for_finding(f, self.config.top_k) for f in findings
            }
        self._record(
            st, "RETRIEVE", t0, f"{sum(len(v) for v in report.retrieved.values())} doc hits"
        )

        # Round 0: initial patch for every file with findings.
        files = sorted({f.file for f in findings})
        st.originals = {f: st.workspace.read(f) for f in files}
        targets = {path: [x for x in findings if x.file == path] for path in files}
        failures: dict[str, str] = {}
        last = ""
        previous: ValidationResult | None = None
        for index in range(self.config.max_repairs + 1):
            t0 = time.monotonic()
            state = "PATCH" if index == 0 else f"REPAIR {index}"
            files = list(targets) if index == 0 else self._files_to_repair(st, targets, failures)
            patches = [
                self._patch_file(
                    st,
                    path,
                    targets[path],
                    None if index == 0 else failures.get(path, last),
                    previous,
                )
                for path in files
            ]
            commit = st.workspace.commit(f"{state.lower()}: {', '.join(files)}")
            self._record(
                st,
                state,
                t0,
                f"{sum(p.applied for p in patches)} edits applied, {sum(p.rejected for p in patches)} rejected",
            )

            t0 = time.monotonic()
            validation = self.validator.validate(st.workspace.root)
            report.rounds.append(
                Round(index=index, patches=patches, validation=validation, commit=commit)
            )
            self._record(st, "VALIDATE", t0, _summary(validation))
            if st.best is None or validation.score() > st.best[0]:
                st.best = (validation.score(), index, commit)
            if validation.passed:
                break
            failures = self._failure_context(st, validation, patches)
            last = f"- validation still failing: {_summary(validation)}"
            previous = validation
        self._finish(st)

    def _finish(self, st: _State) -> None:
        report, ws = st.report, st.workspace
        if ws is None:
            return
        t0 = time.monotonic()
        final = report.rounds[-1] if report.rounds else None
        if final is not None and final.validation.passed:
            report.kept_round = final.index
            report.status = (
                RunStatus.UNVERIFIED if final.validation.stage == "skipped" else RunStatus.SUCCESS
            )
        elif st.best is not None and st.best[1] is not None:
            # Validation still failing: keep the best state seen ("last known-good"), not the last.
            _, best_round, commit = st.best
            if ws.head() != commit:
                ws.restore(commit)
            report.kept_round = best_round
            report.status = RunStatus.PARTIAL
        else:
            # Nothing beat the original: restore it, so the workspace never ends worse.
            ws.restore(ws.baseline)
            report.kept_round = None
            report.status = RunStatus.FAILED
        self._record(st, "SELECT", t0, f"kept round {report.kept_round}")

        t0 = time.monotonic()
        after = analyze(ws.root, self.profile)
        report.residual_findings = after.actionable()
        report.changed_files = ws.changed_files()
        report.diff = ws.diff()
        self._record(st, "RESIDUAL", t0, f"{len(report.residual_findings)} findings remain")

        if self.config.apply_to_original and report.status in (
            RunStatus.SUCCESS,
            RunStatus.UNVERIFIED,
        ):
            ws.apply_to_original()
            report.applied_to_original = True
        if not self.config.keep_workspace:
            ws.cleanup()
            report.workspace = ""

    # -- patching ------------------------------------------------------------------------

    def _repo_notes(self, st: _State) -> str:
        a = st.report.analysis
        models = ", ".join(a.model_classes) or "(none)"
        files = ", ".join(sorted(st.originals))
        return (
            f"Pydantic model classes in this repository: {models}.\nFiles being migrated: {files}."
        )

    def _patch_file(
        self,
        st: _State,
        path: str,
        findings: list[Finding],
        failure: str | None,
        failed_validation: ValidationResult | None = None,
    ) -> FilePatchResult:
        ws = st.workspace
        assert ws is not None
        content = ws.read(path)
        docs = (
            context_for_file(
                st.report.retrieved, [f.id for f in findings], self.config.doc_budget_chars
            )
            if self.retriever is not None
            else []
        )
        args = (self.profile.title, self.profile.system_hint, path, content, findings, docs)
        if failure is None:
            prompt = patch_prompt(*args, repository_notes=self._repo_notes(st))
        else:
            prompt = repair_prompt(*args, failure=failure, repository_notes=self._repo_notes(st))
        answer = request_edits(self.provider, prompt)
        st.report.usage.add(answer.usage)
        if "LLMQuotaExhausted" in answer.error:
            raise LLMQuotaExhausted(answer.error)
        spans = [LineRange(f.line, f.end_line) for f in findings]
        # In repair rounds, the code the failing tests implicate is also in scope
        # (current-content coordinates, re-mapped as this call's edits shift lines).
        base = content
        implicated = (
            repair_ranges(ws.root, failed_validation, path, content)
            if failure is not None and failed_validation is not None
            else []
        )
        outcomes: list[EditOutcome] = []
        for edit in answer.edits:
            scope = scope_for(st.originals[path], content, spans) + [
                map_range(base, content, r) for r in implicated
            ]
            content, outcome = apply_edit(content, edit, scope)
            outcomes.append(outcome)
        if any(o.applied for o in outcomes):
            ws.write(path, content)
        return FilePatchResult(
            file=path, outcomes=outcomes, llm_notes=answer.notes, error=answer.error
        )

    # -- repair --------------------------------------------------------------------------

    def _failure_context(
        self, st: _State, validation: ValidationResult, patches: list[FilePatchResult]
    ) -> dict[str, str]:
        """Per-file failure text for the repair prompt: rejections, syntax errors, test failures."""
        per_file: dict[str, list[str]] = {}
        for p in patches:
            lines = [
                f"- edit rejected ({o.reason}); its search text was:\n{o.edit.search[:400]}"
                for o in p.outcomes
                if not o.applied
            ]
            if p.error:
                lines.append(f"- the model's previous answer could not be used: {p.error}")
            if lines:
                per_file.setdefault(p.file, []).extend(lines)
        for err in validation.syntax_errors:
            per_file.setdefault(err.split(":", 1)[0], []).append(f"- syntax error: {err}")
        failed = [t for t in validation.tests if t.outcome in ("failed", "error")]
        if failed or validation.timed_out:
            text = "\n".join(f"- test {t.nodeid} {t.outcome}:\n{t.message}" for t in failed)
            if validation.timed_out:
                text += "\n- the test run timed out"
            text = text[:MAX_FAILURE_CHARS]
            mentioned = [f for f in st.originals if f in text]
            for f in mentioned or list(st.originals):
                per_file.setdefault(f, []).append(text)
        return {
            f: "\n".join(v)[:MAX_FAILURE_CHARS] for f, v in per_file.items() if f in st.originals
        }

    def _files_to_repair(
        self, st: _State, targets: dict[str, list[Finding]], failures: dict[str, str]
    ) -> list[str]:
        return [f for f in targets if f in failures] or list(targets)


def _summary(v: ValidationResult) -> str:
    if v.stage == "syntax":
        return f"syntax errors: {len(v.syntax_errors)}"
    if v.stage == "skipped":
        return "no tests collected"
    return f"{v.n_passed} passed, {v.n_failed} failed" + (" (timed out)" if v.timed_out else "")


def total_usage(reports: list[RunReport]) -> LLMUsage:
    usage = LLMUsage()
    for r in reports:
        usage.add(r.usage)
    return usage
