Prompt: 04_remaining_use_cases
Version: v1.1
Purpose: Evaluate the generic PatchPilot architecture across the fixed migration benchmark

You are implementing Part 4 of PatchPilot: Additional Supported Migration Use Cases.

Prompts 1–3 are complete. The existing PatchPilot architecture already supports a central state machine, typed schemas, SQLite persistence, Repository Analyzer, Context Manager with ranking and budgets, Migration Planner, Patch Generator, sandbox verification, human approval, target-branch application, Failure Analyzer, a bounded three-attempt repair loop, independent Change Reviewer, progressive context expansion, snapshots and rollback, and model telemetry.

Core rule: Do not redesign or add new core architecture. Prompt 4 exists only to answer whether the same PatchPilot workflow generalizes to migration problems other than Pydantic. Reuse the Prompt 2 happy path and Prompt 3 failure and repair path.

# 1. Store This Prompt

Create docs/prompts/04_remaining_use_cases.md. Store this complete prompt with the metadata above. Runs created for this benchmark must persist prompt_name = 04_remaining_use_cases and prompt_version = v1.1.

# 2. Fixed Benchmark Set

The benchmark set is fixed before evaluation. Do not let Codex or the model choose alternatives. Use exactly these five migration families, and do not substitute easier libraries or change the set during model comparison:

1. Pydantic v1 → v2, already implemented in Prompts 1–3.
2. SQLAlchemy 1.4 → 2.0.
3. HTTPX 0.27 → 0.28 deprecated API migration.
4. OpenAI Python SDK 0.28 → 1.x.
5. Celery 4 → 5 configuration/API migration.

# 3. Four Additional Canonical Fixtures

Create one small canonical Python fixture for each of Use Cases 2–5. Each must use the old dependency and API version, realistic migration-relevant behavior, multiple source files where appropriate, meaningful regression tests, migration-specific verification, pytest, mypy where appropriate, ruff, and runtime/import sanity verification. Each fixture must remain immutable during PatchPilot runs. Keep fixtures small and understandable, without reducing them to trivial search-and-replace examples.

# 4. Reuse the Existing Architecture

Every use case must enter the same Prompt 2 and Prompt 3 workflow.

Happy path:
INITIAL → RECEIVED → SCOPE_CHECK → ANALYZING_REPO → CONTEXT_BUILDING → PLANNING → PATCH_GENERATING → PATCHING_SANDBOX → VERIFYING_SANDBOX → VERIFIED_PATCH_READY → AWAITING_APPROVAL → APPROVED → APPLYING_TO_TARGET_BRANCH → VERIFYING_TARGET_BRANCH → READY_FOR_PR.

Failure path:
VERIFYING_SANDBOX → ANALYZING_FAILURE → REPAIR_PROPOSED → direct approval or AWAITING_REVIEW → REPAIR_APPROVED → REPAIRING → VERIFYING_SANDBOX.

Enforce three total attempts at most. Attempt 3 failure must reach NEEDS_HUMAN_REVIEW. Do not create migration-specific state machines.

# 5. Do Not Hard-Code Migration Reasoning

Do not write migration-specific hardcoded solutions in orchestration. Library-specific fixture setup and migration-specific verification checks are allowed. Reasoning about affected files, required changes, patch generation, failure diagnosis, and repair must continue through the existing generic PatchPilot workflow.

# 6. Repository Analysis Must Generalize

Reuse deterministic filesystem discovery, ripgrep, Python AST, dependency/config parsing, test discovery, and import/reference relationships. Do not add one-off scanners unless they genuinely belong to generic dependency/config analysis. Persist evidence explaining why candidate files were selected.

# 7. Context Manager Must Generalize

Continue candidate retrieval, deterministic relevance ranking, and independent max_files, max_snippets, and max_context_tokens limits. Do not raise context budgets merely because a fixture is harder. Continue progressive context expansion during repair. Persist selected context, ranking reasons, context size, and expansion history.

# 8. Happy Path for Every New Use Case

For each Use Case 2–5, execute at least one controlled-model end-to-end migration. Use a real sandbox, real dependency/version migration environment, real verification commands, simulated human approval, exact verified patch reuse, new target migration branch, and complete re-verification. Successful runs must reach READY_FOR_PR. Canonical fixtures and target main/default branches remain unchanged.

# 9. Failure and Repair Paths

For each migration family, create at least one meaningful controlled failure scenario where feasible; do not invent meaningless failures merely for coverage. Across the fixed suite, cover:
A. Attempt 1 FAIL → Attempt 2 PASS.
B. Attempt 1 FAIL → Attempt 2 FAIL → Attempt 3 PASS.
C. Attempt 1 FAIL → Attempt 2 FAIL → Attempt 3 FAIL → NEEDS_HUMAN_REVIEW.

Cover both clear-evidence deterministic Orchestrator approval and ambiguous/risky independent Change Reviewer approval. At least one case must exercise Reviewer NEED_MORE_EVIDENCE → Context Manager expansion → reevaluation.

# 10. Preserve Safety Rules

Do not weaken sandbox-only patching before approval, exact verified patch reuse, regression-test protection, approved-file scope enforcement, the three-attempt cap, stable and candidate checkpoint semantics, repair-base rollback semantics, context-expansion exhaustion, target-main preservation, or the human approval gate. Reuse these mechanisms without redesign.

# 11. Model Strategy

Use the existing controlled/fake model for deterministic automated end-to-end evaluation. Live Sol evaluation remains deferred until Prompt 6. Do not optimize models or compare Sol and Terra in Prompt 4.

# 12. Persist Benchmark Results

For every run persist use_case, migration_family, run_id, final_state, attempt_count, Reviewer invocation, context expansions, files changed, verification results, rollback events, model-call count, token metadata if available, latency metadata, and cost metadata if available. Clearly identify controlled runs with model_type = test_double. Do not fabricate real API token or cost measurements.

# 13. Benchmark Summary

Produce artifacts/benchmark/prompt4_summary.json and/or prompt4_summary.md. For all five migrations include migration, happy-path final state, attempts required, repair path exercised, Reviewer usage, context expansion usage, verification outcome, and known limitations. The summary will feed later evaluation and README work.

# 14. Required Tests

Automated tests must prove:
- SQLAlchemy, HTTPX, OpenAI SDK, and Celery fixtures start healthy and use the intended old dependency/API baselines.
- Every use case traverses the same central state machine and no migration-specific orchestration appears.
- Each happy path reaches READY_FOR_PR.
- Canonical fixtures and target main/default branches stay unchanged.
- The exact sandbox-verified patch is reused.
- Repair paths enforce three attempts at most.
- Deterministic approval and Reviewer approval work on non-Pydantic cases.
- Progressive context expansion respects budgets.
- Persistence records migration family and run result.
Tests must assert intermediate transitions where relevant, not only terminal states.

# 15. Do Not Expand Scope

Do not implement Python → Java migration, arbitrary new-feature development, large architecture refactors, production deployment, automatic merge, Prompt 5 guardrail/system-failure suite, Prompt 6 model optimization, Sol/Terra comparison, LangGraph, vector database, or UI.

# Acceptance Criteria

Before finishing, confirm:
- Exactly the agreed five migration families are fixed.
- Four new canonical fixtures exist and start from healthy baselines.
- Existing Prompt 2/3 architecture is reused without a new core workflow.
- Every new migration has a controlled-model happy-path end-to-end run reaching READY_FOR_PR.
- Prompt 3 failure and repair logic is exercised across the benchmark, including all three attempt outcomes, deterministic and Reviewer approval, and context expansion.
- Canonical fixtures and target main/default branches remain unchanged.
- Benchmark results are persisted.
- No real OpenAI API key is required and no Prompt 5/6 functionality was implemented.

# Final Response

Report concisely: files created or changed; four fixtures; exact dependency/API baseline for each; happy-path result for each migration; failure and repair paths; Reviewer and context-expansion cases; attempt counts and terminal states; verification results; benchmark summary location; limitations before Prompt 5.

# Final v1.1 Genericization Requirements

The core migration engine must consume migration-family configuration rather than assuming Pydantic. The fixed five-family benchmark remains unchanged. Every Prompt 4 benchmark run persists `prompt_name = 04_remaining_use_cases` and `prompt_version = v1.1`.

Family metadata supplies the dependency name, source and target versions, source and target dependency declarations, deprecated API and search patterns, expected runtime import/check, target dependency verification check, shared base symbols where relevant, and branch and commit labels. These library-specific values belong in benchmark configuration, not in core analyzer, verifier, or orchestrator branches.

The RepositoryAnalysis contract uses generic `dependency_name`, `dependency_version`, `source_version`, `target_version`, `migration_family`, and `migration_api_usages` fields. It must not default to Pydantic. The Repository Analyzer reads family configuration and combines filesystem discovery, ripgrep, AST, dependency parsing, test discovery, and import/reference evidence. Context selection continues to use independent file, snippet, and token budgets.

The Verification Runner executes the configured target dependency/version check and runtime/import check, plus migration API/dependency validation, pytest, mypy, and ruff. A failed target dependency/version check is an `ENVIRONMENT_ERROR` for any of the five families; it must not enter the repair loop. Migration branches and commit messages derive from family metadata. The exact sandbox-verified patch, human approval, target-main protection, three-attempt repair limit, state machine, SQLite persistence, and telemetry remain unchanged.

Add tests for generic branch/commit naming, missing target dependency classification for Pydantic, SQLAlchemy, and HTTPX, generic schema/analyzer/verifier behavior, and preservation of the Pydantic happy path. Rerun the fixed five-family benchmark with happy paths and existing repair, Reviewer, and context-expansion coverage. Persist generic dependency/version fields in the benchmark artifacts. Do not add Prompt 5 or Prompt 6 behavior.
