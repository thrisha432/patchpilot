# Changelog

## v0.2.1: real-repository evaluation

* **Real-repository benchmark** (`benchmarks/run_real.py`, `bench/real.py`).
  Three open-source projects at their pre-migration commit, scored
  against the maintainers' post-migration tests. Systems never see those
  tests. Deprecations count as errors only when raised from the package's
  own modules.
* **Fix: best-state selection** (`ValidationResult.score`). Test modules
  that fail to import now rank worse than any number of failing tests.
  Before, fixing imports that let 15 modules load (and their tests fail
  individually) looked like a regression, and PatchPilot restored the
  original code.
* **New baseline `direct-llm-guarded`.** It is the direct prompt, but it
  keeps a file unchanged when the answer does not parse. This keeps the
  comparison fair: on real code, most of the plain prompt's failures were
  non-code answers.
* **Uncertainty** (`benchmarks/stats.py`): Wilson intervals, an exact
  McNemar test and a task-level sign test.
* tree-sitter pinned below 0.26: 0.26.0 segfaults on some real files. A
  regression test covers this.

## v0.2: changes driven by the tier-2 benchmark

The frozen v0.1 run on tier 2 (harder, more realistic tasks) solved 12/27
runs, while the direct-prompt baseline solved 20/27. Every v0.1 failure had
the same root cause: **PatchPilot only edited where its analyzer pointed**,
and it refused to act on test evidence elsewhere. Fixes:

* **Test-guided repair scope** (`migration/scope_hints.py`). During repair,
  edits may also land on lines named in a failing traceback, and on the
  definitions that failing tests import and call, plus the module-level names
  those read (one level). Task 28 needed this: the v1-era lookup table it had
  to change sits far from any finding. Round 0 is still confined to findings.
* **Discovery covers missed deprecations** (`migration/discovery.py`). v0.1
  skipped every deprecation failure, assuming the static rules had it. Now
  only locations those rules already explain are skipped, including the
  `class X(BaseModel):` header line where class-creation errors surface.
* **Analyzer gaps closed** (`profiles/pydantic_v2/detector.py`):
  validators applied without decorator syntax (`validator("a",
  allow_reuse=True)(fn)`); deprecated methods passed by reference
  (`map(User.parse_obj, rows)`, `return event.json`); generic return
  annotations (`-> Page[Item]`); and repository classes that are not models
  (`Snapshot.parse_obj`, a v0.1 false positive).

Result: tier 2 went from 12/27 to 27/27 runs solved, with tier 1 unchanged
at 69/69. Because v0.2 was fixed *after* seeing tier 2, a **held-out tier 3**
was written after the v0.2 code was frozen, then run once. See
[docs/BENCHMARK_REPORT.md](docs/BENCHMARK_REPORT.md).

## v0.1: first complete pipeline

Repository analyzer (tree-sitter, cross-file model resolution, receiver type
inference with confidence levels), BM25 retrieval over the official migration
guide, search/replace patches with a scope guard, git-tracked isolated
workspace, locked-down Docker validation with deprecations as errors, up to
two repairs with best-state selection, test-driven discovery, Markdown/JSON
reports, Typer CLI, FastAPI job API, Gemini and Claude Code providers, and a
benchmark harness with a rule-based baseline (bump-pydantic) and a
direct-prompt baseline.
