"""Render a RunReport as Markdown (for humans and PRs) or JSON (for tools).

Everything shown is read from the run's recorded results; nothing is computed
from assumptions. Each edit is traced back to the finding it addresses and the
documentation that was retrieved for that finding.
"""

from __future__ import annotations

from patchpilot.models import (
    Confidence,
    EditOutcome,
    Finding,
    RunReport,
    RunStatus,
    ValidationResult,
)

STATUS_TEXT = {
    RunStatus.SUCCESS: "✅ Validation passed",
    RunStatus.PARTIAL: "⚠️ Partially migrated: validation still failing (best state kept)",
    RunStatus.FAILED: "❌ Failed: original code kept",
    RunStatus.NOTHING_TO_DO: "⏹️ Nothing to migrate",
    RunStatus.UNVERIFIED: "⚠️ Applied, but the repository has no tests to verify it",
    RunStatus.UNSUPPORTED: "⏹️ Unsupported repository",
}


def _validation_line(v: ValidationResult | None) -> str:
    if v is None:
        return "not run"
    if v.stage == "syntax":
        return f"syntax errors ({len(v.syntax_errors)})"
    if v.stage == "skipped":
        return "no tests collected"
    verdict = "passed" if v.passed else "failed"
    extra = " (timed out)" if v.timed_out else ""
    return f"{verdict}: {v.n_passed} passed, {v.n_failed} failed{extra}"


def _finding_ids_for(outcome: EditOutcome, file: str, findings: list[Finding]) -> list[str]:
    """The ids the model cited, or (if it cited none) findings whose span holds the edit."""
    if outcome.edit.finding_ids:
        return outcome.edit.finding_ids
    if outcome.start_line is None:
        return []
    line = outcome.start_line
    return [f.id for f in findings if f.file == file and f.line - 2 <= line <= f.end_line + 2]


def to_json(report: RunReport) -> str:
    return report.model_dump_json(indent=2)


def to_markdown(report: RunReport, include_diff: bool = True) -> str:
    a = report.analysis
    actionable = [*a.actionable(), *report.discovered_findings]
    residual_ids = {f.id for f in report.residual_findings}
    applied = sum(p.applied for r in report.rounds for p in r.patches)
    rejected = sum(p.rejected for r in report.rounds for p in r.patches)
    py_files = [f for f in a.files if not f.is_test]
    test_files = [f for f in a.files if f.is_test]
    u = report.usage

    out = [
        "# PatchPilot migration report",
        "",
        f"**{STATUS_TEXT[report.status]}**" + (f": {report.message}" if report.message else ""),
        "",
        "| | |",
        "|---|---|",
        f"| Repository | `{report.repo}` |",
        f"| Migration | {report.profile} |",
        f"| Model | `{report.model}` |",
        f"| Scanned | {len(py_files)} source files, {len(test_files)} test files |",
        f"| Needs migration | {len(a.files_to_migrate())} files, {len(actionable)} findings "
        f"({sum(f.confidence is Confidence.HIGH for f in actionable)} high, "
        f"{sum(f.confidence is Confidence.MEDIUM for f in actionable)} medium confidence) |",
        f"| Edits | {applied} applied, {rejected} rejected |",
        f"| Tests before | {_validation_line(report.baseline_validation)} |",
        f"| Tests after | {_validation_line(report.final_validation)} |",
        f"| Repair attempts | {report.repair_attempts} |",
        f"| Remaining findings | {len(report.residual_findings)} |",
        f"| LLM usage | {u.calls} calls, {u.prompt_tokens:,} prompt + {u.completion_tokens:,} output tokens |",
        f"| Time | {report.seconds:.1f} s |",
        "",
    ]

    if actionable:
        out += ["## Findings", "", "| Finding | Line | Confidence | Status |", "|---|---|---|---|"]
        for f in actionable:
            status = "remaining" if f.id in residual_ids else "resolved"
            out.append(f"| {f.title} — `{f.file}` | {f.line} | {f.confidence.value} | {status} |")
        out.append("")

    for rnd in report.rounds:
        title = "Initial patch" if rnd.index == 0 else f"Repair attempt {rnd.index}"
        kept = " (kept)" if rnd.index == report.kept_round else ""
        out += [f"## {title}{kept}", "", f"Validation: {_validation_line(rnd.validation)}", ""]
        for p in rnd.patches:
            out.append(f"### `{p.file}`")
            if p.error:
                out.append(f"- ⚠️ model error: {p.error}")
            for o in p.outcomes:
                mark = "applied" if o.applied else f"**rejected**: {o.reason}"
                if o.applied and o.reason:
                    mark += f" ({o.reason})"
                where = f"line {o.start_line}" if o.start_line else "?"
                out.append(f"- {where}, {mark}. {o.edit.explanation}")
                docs = {
                    d.chunk.heading
                    for fid in _finding_ids_for(o, p.file, actionable)
                    for d in report.retrieved.get(fid, [])[:1]
                }
                if docs:
                    out.append(f"  - Docs: {'; '.join(sorted(docs))}")
            if p.llm_notes:
                out.append(f"- Model notes: {p.llm_notes}")
            out.append("")
        failing = [t for t in rnd.validation.tests if t.outcome in ("failed", "error")]
        if failing:
            out.append("<details><summary>Failing tests</summary>\n")
            for t in failing[:10]:
                first = (t.message.splitlines() or [""])[0]
                out.append(f"- `{t.nodeid}`: {first[:200]}")
            out.append("\n</details>\n")

    review = [f for f in a.findings if f.confidence is Confidence.LOW]
    if report.residual_findings or review:
        out += ["## Needs human review", ""]
        for f in report.residual_findings:
            out.append(f"- Not migrated: {f.title} at `{f.file}:{f.line}`: {f.message}")
        for f in review:
            out.append(f"- Possibly affected (not changed): `{f.file}:{f.line}`: {f.message}")
        out.append("")

    if include_diff and report.diff:
        out += ["## Diff", "", "```diff", report.diff.rstrip(), "```", ""]
    if report.workspace:
        out.append(f"Workspace with full git history: `{report.workspace}`")
    return "\n".join(out) + "\n"
