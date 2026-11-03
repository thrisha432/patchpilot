# Benchmark report

**Question:** does PatchPilot's architecture (analysis, retrieval, scoped
edits, sandboxed validation, repair) migrate code more reliably than giving
the same model the file and asking it to migrate?

**Short answer, with Claude Haiku 5.5:** on easy single-pattern tasks, no.
Both solve nearly everything. On realistic tasks, yes:

* on the **held-out** set (written after the code was frozen, run once),
  PatchPilot solved **24/24** runs versus **19/24** for the direct prompt;
* PatchPilot **never** broke code outside the migration: 0 regressions and
  0 collateral files across all 120 runs (360 including the ablations).
  The direct prompt did both, on exactly the tasks designed to catch it.
* With **Claude Sonnet 5.5** the direct prompt improves only slightly
  (76% → 84% on tiers 2–3) and fails the same way, while PatchPilot stays
  at 100%.

All numbers below come from `benchmarks/results/` and can be regenerated
(see [Reproducing](#reproducing)).

## Method

### Tasks: 40, in three tiers

| Tier | Tasks | What they are | When written |
|---|---|---|---|
| 1 | 23 | One or two Pydantic v1 patterns each, in small projects (`01`–`23`) | before any system ran |
| 2 | 9 | Realistic: a 240-line module, look-alike non-Pydantic classes across files, behavior changes with no deprecated API (int→str coercion, smart unions, changed error messages), uncommon syntax (validators without `@`, methods passed by reference), a six-file app (`24`–`32`) | after tier-1 results, **before** any system ran on them |
| 3 | 8 | **Held-out:** Pydantic dataclasses, `const` discriminators, PATCH semantics, `always=True` validators, alias generators, subclass serialization, `Decimal` JSON output, a multi-file service with decoys (`33`–`40`) | **after PatchPilot v0.2 was frozen**; run once |

Each task has the v1 project, visible tests (which systems may run), hidden
tests (which only the evaluator runs), and a hand-written v2 reference
solution. `benchmarks/validate_tasks.py` checks every task before any result
on it is trusted:

1. the original passes all tests on Pydantic v1 (the task's code is correct);
2. the original **fails** on Pydantic v2 (the migration is necessary);
3. the reference solution passes all tests on v2 (the task is solvable).

All 40 tasks pass all three checks. The analyzer reports 0 findings on every
reference solution, so it raises no false positives on correct v2 code.

### Systems

| System | Description |
|---|---|
| **PatchPilot** | the full pipeline (see [ARCHITECTURE.md](ARCHITECTURE.md)) |
| PatchPilot without docs | ablation: no retrieved documentation in prompts |
| PatchPilot without repair | ablation: one patch round, no repairs |
| **Direct prompt** | the same model receives each source file with "migrate this file" and returns the whole file, which is applied as-is: no analysis, no docs, no tests. What a developer gets from a chat window. |
| bump-pydantic | Pydantic's official rule-based codemod (no LLM) |

The model is **Claude Haiku 5.5** (`claude-haiku-5-5`), called through Claude
Code's headless mode. A comparison with Claude Sonnet 5.5 is below. There
are **3 repetitions** per (task, system), because the CLI exposes no
temperature setting and answers vary between runs.

### Scoring (identical for every system)

* **Solved:** visible **and** hidden tests pass on Pydantic v2, with
  Pydantic's deprecation warnings turned into errors. Code that merely still
  runs through v2's v1-compatibility shims does not count.
* **Regression:** visible tests pass but hidden tests fail. The change
  *looks* done and isn't.
* **Collateral files:** files changed that the reference solution leaves
  alone.
* **Integrity:** before scoring, the original test files are restored,
  whatever the system did to them. Hidden tests are mounted read-only from
  outside the repository, so no system ever sees them. Tests run in the
  locked-down sandbox.

## Results (PatchPilot v0.2, Claude Haiku 5.5, 3 repetitions)

![Solve rate by tier](images/solve_rate.png)

### Tier 3: held-out (8 tasks × 3 = 24 runs)

| System | Solved | Regressions | Collateral files | Lines changed (reference: 282) | LLM calls / task | Repairs / task |
|---|---|---|---|---|---|---|
| **PatchPilot** | **24/24 (100%)** | 0 | 0 | 275 | 1.6 | 0.46 |
| PatchPilot without docs | 23/24 (96%) | 0 | 0 | 271 | 1.7 | 0.54 |
| PatchPilot without repair | 14/24 (58%) | 0 | 0 | 192 | 1.1 | 0 |
| Direct prompt | 19/24 (79%) | **2** | 0 | 314 | 1.25 | n/a |
| bump-pydantic | 0/8 (0%) | 0 | 0 | 24 | 0 | n/a |

### Tier 2: realistic (9 tasks × 3 = 27 runs)

| System | Solved | Regressions | Collateral files | Lines changed (reference: 294) |
|---|---|---|---|---|
| **PatchPilot** | **27/27 (100%)** | 0 | 0 | 309 |
| PatchPilot without docs | 27/27 (100%) | 0 | 0 | 318 |
| PatchPilot without repair | 18/27 (67%) | 0 | 0 | 231 |
| Direct prompt | 20/27 (74%) | **2** | **2** | 416 |
| bump-pydantic | 0/9 (0%) | 0 | 0 | 61 |
| *PatchPilot v0.1 (before the fixes below)* | *12/27 (44%)* | *0* | *0* | *209* |

### Tier 1: single-pattern (23 tasks × 3 = 69 runs)

| System | Solved | Lines changed (reference: 624) |
|---|---|---|
| PatchPilot | 69/69 (100%) | 629 |
| PatchPilot without docs | 69/69 (100%) | 622 |
| PatchPilot without repair | 69/69 (100%) | 629 |
| Direct prompt | 68/69 (99%) | **798** (+28%) |
| bump-pydantic | 4/23 (17%) | 122 |

Tier 1 does not separate the LLM systems: Haiku 5.5 handles a single
deprecated pattern in a small file whichever way it is asked. That tier is
kept as a sanity check, not as evidence.

![Runs solved per task](images/task_matrix.png)

## What the failures show

**Direct prompt: two failure modes, both structural.**

1. *It renames look-alike methods on classes that are not Pydantic models.*
   `Record.dict()`, `LRU.dict()`, and `AuditLog.copy()` became
   `.model_dump()` / `.model_copy()`, which then crashed with
   `AttributeError`. Seen per file, these calls are indistinguishable from
   Pydantic calls; only another file says otherwise. In 4 runs the visible
   tests still passed, so the change looked done, and only the hidden tests
   caught it. Once, rewriting the legacy module produced invalid syntax.
2. *It cannot see behavior changes, because it never runs the code.* It
   failed every run of `26` (v2 stops coercing ints to `str` fields) and
   every run of `39` (v2 serializes `Decimal` as a JSON string).

It also rewrites more than needed: 28% more lines than the reference on
tier 1. Once (task `01`) it deleted a class that the tests import.

**PatchPilot: where the parts earn their place.**

* **Repair is the largest single factor:** 67% → 100% on tier 2 and 58% →
  100% on held-out tier 3. All 19 runs that needed a repair passed after
  it. The fixes came from real test output: a `NameError` for a missing
  import, smart-union coercion, error-message codes, `Decimal` JSON.
* **Test-driven discovery** solved task `33` (Pydantic *dataclasses*), a
  feature the analyzer has **no rules for**. The baseline failure located
  the code, and the repair loop fixed it.
* **Retrieved documentation** helps a little on this model: one failure
  without it (task `33`, a dataclass config the model got wrong once) and
  slightly smaller diffs. With a stronger model the docs matter less. They
  are the cheapest part of the pipeline to keep, and they make every edit
  explainable (each report cites the guide section behind it).
* **The analyzer + scope guard** are why there are 0 regressions and 0
  collateral changes: edits land only where findings or failing tests point,
  and receivers that are provably not models are never touched.

**bump-pydantic** solves 4/40 tasks. That is by design rather than poor
quality: it deliberately does not rewrite method calls like `.dict()`,
because without type information it cannot know whether the receiver is a
model. That is precisely the gap PatchPilot's repo-wide receiver inference
closes.

## v0.1 → v0.2: what the benchmark changed

The frozen v0.1 run on tier 2 solved only **12/27** runs, fewer than the
direct prompt (20/27). The failures had one root cause: **PatchPilot only
edited where its analyzer pointed.** When a failing test pointed somewhere
else, the scope guard rejected the fix. The changes, all general rather
than task-specific (details in [CHANGELOG.md](../CHANGELOG.md)):

| v0.1 failure | Fix in v0.2 |
|---|---|
| `28`: the fix lives in a lookup table far from any finding, so the repair was rejected as out of scope | **Test-guided repair scope:** repairs may edit lines a failing traceback names, and the definitions (plus module-level names they read) that failing tests import |
| `30`, `31`: validator without `@`, methods passed by reference, so the analyzer found nothing and nothing changed | Analyzer rules for both; **discovery** now also catches deprecation failures the rules miss |
| `32`: a `.json()` on a generic model, missed | Generic return annotations resolved (`-> Page[Item]`) |
| `25`: false positive on a non-model `Snapshot.parse_obj` | Repository classes that are not models are never flagged |

v0.2 solves 27/27 on tier 2. Because those fixes were made *after* seeing
tier 2, **tier 2 is not a fair test of v0.2.** That is what tier 3 is for:
written after v0.2 was frozen, run once, and reported above as it came out.

## Model comparison: Claude Sonnet 5.5

Does a stronger model make the architecture unnecessary? PatchPilot and the
direct prompt were re-run on tiers 2 and 3 (17 tasks × 3 repetitions) with
**Claude Sonnet 5.5** (`claude-sonnet-5-5`):

| Tiers 2 + 3 | PatchPilot | Direct prompt | Direct-prompt regressions | Est. cost per task, PatchPilot / direct |
|---|---|---|---|---|
| Claude Haiku 5.5 | **51/51 (100%)** | 39/51 (76%) | 4 | ≈ $0.002 / $0.001 |
| Claude Sonnet 5.5 | **51/51 (100%)** | 43/51 (84%) | 3 | ≈ $0.032 / $0.012 |

* The stronger model narrows the gap only slightly, and **its failures are
  the same structural ones**. It renamed `Record.dict()` (not a Pydantic
  model) in all 3 runs of `25`, renamed `LRU.copy()` once, and produced
  string `Decimal`s in all 3 runs of `39`. Those come from the method (one
  file at a time, code never run), not from the model's ability.
* **PatchPilot with the cheaper model beats the direct prompt with the
  stronger one:** 100% vs 84%, at roughly a sixth of the per-task cost.
* With Sonnet, PatchPilot's diffs match the reference size exactly (576 vs
  576 lines). The direct prompt's are 22% larger (705).

Cost estimates use list prices ($0.10/$0.50 per million input/output
tokens for Haiku 5.5, $2/$10 for Sonnet 5.5) on the recorded token counts,
ignoring cache pricing. The runs used a Claude subscription, so these are
equivalents, not money spent.

## Cost and time

| | PatchPilot | Direct prompt |
|---|---|---|
| LLM calls per task (tier 3) | 1.6 | 1.25 |
| Tokens per task (tier 3) | ~10.7k | ~3.1k |
| Equivalent API cost per task at Haiku 5.5 list price | ≈ $0.002 | ≈ $0.0007 |
| Model time per task (tier 3) | 11.4 s | 5.7 s |
| Docker validation per run | ~0.5 s per test run | none |

PatchPilot uses about 3.5× the tokens, mostly the retrieved documentation
and the findings. At Haiku prices, migrating all 40 tasks costs well under
10 cents. The runs themselves used a Claude subscription, so the dollar
figures are list-price equivalents computed from token counts (cache
pricing ignored), not money spent.

## Limitations (read these before quoting a number)

* **I wrote the tasks and the system.** Tier 3 was written after the code
  was frozen to limit this bias, but it was still written by the system's
  author, who knows its design. Independent tasks would be stronger.
* **Small n.** 40 tasks, 3 repetitions. Differences of one or two runs
  are noise. The direct prompt's failures cluster on specific task types
  (look-alike methods, behavior changes) rather than spreading randomly,
  which is what makes them meaningful.
* **One migration, one model family.** Pydantic v1 → v2 only, and Claude
  models only (Haiku 5.5 for everything, Sonnet 5.5 for tiers 2–3). A
  stronger model narrows the gap a little (see the Sonnet comparison).
* **Synthetic projects.** Realistic in shape, but small. Real repositories
  have dependencies the sandbox would need to install.
* **The no-repair ablation reuses** the full system's cached first-round
  answer within each repetition (identical prompt). That makes it a paired
  comparison of exactly the repair step, but it also means its wall time is
  not comparable.

## Reproducing

```bash
patchpilot sandbox build
.venv/bin/python benchmarks/validate_tasks.py                 # 40/40 valid
.venv/bin/python benchmarks/run_benchmark.py \
    --model claude-code:claude-haiku-5-5 --reps 3 --out benchmarks/results/mine.jsonl
.venv/bin/python benchmarks/summarize.py benchmarks/results/mine.jsonl --tier 3
```

Model answers are cached in `benchmarks/.llm-cache/`, so a re-run with the
same prompts replays the recorded answers and costs nothing. Any other
provider works too (`--model gemini:gemini-2.5-flash` with a free Gemini
key).
