# Security model

PatchPilot is a **portfolio and learning project**, not production-certified
tooling. It was still designed around one assumption: *both the repository
being migrated and the LLM's output are untrusted.*

## Threats and mitigations

| Threat | Mitigation | Tested in |
|---|---|---|
| Repository tests run malicious code | Tests run only inside Docker: `--network none`, `--cap-drop ALL`, `no-new-privileges`, read-only root and workspace, `tmpfs /tmp`, memory/CPU/PID limits, non-root user, wall-clock kill | `tests/integration/test_sandbox.py` |
| Sandbox exfiltrates secrets (API keys) | No host environment variables are passed into the container; there is no network | `test_host_environment_is_not_visible`, `test_no_network` |
| LLM edits weaken or delete tests to "pass" | The workspace refuses writes to test files, and the benchmark evaluator restores the original tests before scoring | `test_refuses_tests_and_escaping_paths`, `bench/evaluate.py` |
| LLM edits unrelated code | Search text must match exactly once and land within a finding's span or the imports; whole-file replacements are refused; the model never chooses which file it edits | `tests/unit/test_edits.py` |
| Path traversal or symlink escape | Workspace paths are resolved and confined; symlinks are copied as links and never followed when reading or writing | `test_symlinks_are_not_followed` |
| Original repository damaged | Runs happen in a copy. `--apply` writes back only after validation passes, and only if every file still has its original hash (atomic per-file replace) | `test_apply_to_original_checks_for_concurrent_changes` |
| User's git hooks/signing run during migration | Workspace git ignores global/system config and disables hooks | `test_user_git_config_is_ignored` |
| API reads arbitrary directories | `repo_path` must resolve (after symlinks and `..`) under `PATCHPILOT_ALLOWED_ROOTS`; the API binds to 127.0.0.1 by default and never writes to the original | `test_paths_outside_allowed_roots_are_refused` |
| Surprise LLM charges | Gemini: free tier, and a daily-quota error stops the run (no paid fallback). Claude Code: runs under the user's subscription, and `ANTHROPIC_API_KEY` is stripped from its environment so an API account is never billed | `test_daily_quota_is_not_retried_and_never_falls_back`, `test_structured_answer_usage_and_isolation` |
| API key leaks | Keys come from the environment or a git-ignored `.env`; the Gemini key travels in a header, never a URL; `doctor` reports whether a key is set, never its value; CI runs gitleaks | `test_success_parses_text_usage_and_request_shape` |

## Data handling

Code sent to a hosted model leaves the machine. With the Gemini **free
tier**, Google may use submitted data to improve its products. Only run
PatchPilot on public or sample code with it. The benchmark tasks in this
repository are synthetic.

## Known limitations

* Docker isolation is not a VM boundary. A kernel or container-runtime escape
  is out of scope.
* The sandbox image is built with network access (to install pinned
  packages); only test execution is offline.
* The HTTP API has no authentication. It is meant for local use on
  127.0.0.1.

## Reporting

This is a personal portfolio repository. Please open an issue for anything
security-relevant.
