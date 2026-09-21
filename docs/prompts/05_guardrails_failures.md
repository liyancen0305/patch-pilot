Prompt: 05_guardrails_failures
Version: v1
Purpose: Capability guardrails, unsupported requests, and system/model/tool/environment failure handling

You are implementing Part 5 of PatchPilot: Capability Guardrails and Non-Migration Failure Handling. Prompts 1–4 are complete. Reuse the existing generic Python migration architecture, central state machine, typed schemas, SQLite persistence, Repository Analyzer, Context Manager, planner and patch generator, sandbox verification, bounded three-attempt repair, independent Change Reviewer, snapshots and rollback, approval, target re-verification, and fixed five-family benchmark. Do not redesign these workflows.

# Goal

Distinguish supported migrations, unsupported requests, semantically ambiguous requests, requests that cannot be safely verified, unsafe or out-of-scope AI proposals, model failures, tool failures, environment failures, and normal migration verification failures. Only genuine migration/code correctness failures may enter the Prompt 3 repair loop.

# 1. Prompt identity

Store this complete Prompt 5 contract at `docs/prompts/05_guardrails_failures.md`. Runs involving Prompt 5 persist `prompt_name = 05_guardrails_failures` and `prompt_version = v1`.

# 2. Central state machine

Extend the same authoritative state machine with `CAPABILITY_CLASSIFYING`, `VERIFICATION_CAPABILITY_CHECK`, `SCOPE_VIOLATION`, `UNSUPPORTED`, and `VERIFICATION_FAILURE`. Continue using `MODEL_ERROR`, `TOOL_ERROR`, `ENVIRONMENT_ERROR`, `FAILED_SYSTEM`, `NEEDS_HUMAN_REVIEW`, and `ANALYZING_FAILURE`. Every transition explicitly persists previous state, trigger/event, component, next state, timestamp, and attempt number when applicable. Invalid transitions are rejected; no state change is implicit.

# 3. Deterministic-first Capability Gate

Resolve clearly supported and clearly unsupported requests without an LLM. Deterministic unsupported rules include non-Python or cross-language rewrites, production deployment, destructive production database actions, explicit new-feature development, repositories outside the permitted workspace, and explicit architectural redesign. A clearly supported request follows `RECEIVED → SCOPE_CHECK → VERIFICATION_CAPABILITY_CHECK`; sufficient verification then follows `VERIFICATION_CAPABILITY_CHECK → ANALYZING_REPO`. A clearly unsupported request follows `SCOPE_CHECK → UNSUPPORTED`.

# 4. Ambiguous semantic classification

For a genuinely ambiguous request such as “Modernize this legacy authentication module,” follow `SCOPE_CHECK → CAPABILITY_CLASSIFYING` and invoke a dedicated `CapabilityClassifier` through the shared model client. It is separate from Migration Planner, Failure Analyzer, and Change Reviewer. Require a schema-valid `CapabilityClassification` containing `classification` (`SUPPORTED_MIGRATION`, `UNSUPPORTED`, or `NEED_MORE_INFORMATION`), `reason`, `detected_migration_type`, `scope_risk`, and `missing_information`. Supported follows `CAPABILITY_CLASSIFYING → VERIFICATION_CAPABILITY_CHECK`; unsupported follows `CAPABILITY_CLASSIFYING → UNSUPPORTED`; missing information follows `CAPABILITY_CLASSIFYING → NEEDS_HUMAN_REVIEW`. Do not invent missing intent. Malformed classifier output enters model-error handling.

# 5. Unsupported requests

Test Python → Java rewrite, new payment feature, large architectural redesign, automatic production deployment, and destructive production database migration. `UNSUPPORTED` is terminal. Return typed reason, detected request type, violated scope rule, and a supported alternative where appropriate. Do not invoke planner, patch generator, or repair generator.

# 6. Verification capability

Before planning, confirm objective verification in the configured verification environment: migration-specific checks, regression tests, pytest, mypy when required, ruff, runtime/import sanity, and the required target dependency/version. If sufficient objective verification is absent, follow `VERIFICATION_CAPABILITY_CHECK → NEEDS_HUMAN_REVIEW` with reason “cannot safely verify migration.” An unavailable or corrupted verification interpreter or target dependency is an environment failure. The model cannot declare success in place of deterministic verification.

# 7. Hard scope violations

At planning, patching, failure analysis, or repair, deterministic guardrails inspect proposed actions. Block repository/workspace escape, test deletion or weakened assertions, expected-value or business-behavior changes merely to pass, production credential edits, automatic deployment, destructive production actions, and unsupported architecture redesign. Follow `current state → SCOPE_VIOLATION → NEEDS_HUMAN_REVIEW`. Do not apply the patch and do not ask the AI Reviewer to approve a hard violation. Ambiguous but potentially valid repair scope expansion continues through the Prompt 3 independent Reviewer.

# 8. Model failures and retries

Handle timeout, rate limit, unavailable provider, malformed structured output, schema validation errors, and missing required fields. Model calls use a small deterministic retry policy; persist component, model, error type, retry count, and message. A retryable call follows `current AI state → MODEL_ERROR → previous workflow state` before retry. Exhaustion follows `MODEL_ERROR → FAILED_SYSTEM`. Do not edit application code because model infrastructure failed. Every model call, including the classifier, uses the shared client and telemetry with model, prompt/version, structured output, tokens, latency, cost when available, and error.

# 9. Tool and environment failures

Handle file read/write, Git, patch application, search, and SQLite failures as tool failures; sandbox creation, dependency setup, unavailable verification Python, test-runner startup, permissions, and missing target dependency as environment failures. Persist typed failure and retry/recovery records. A recoverable deterministic failure follows `current state → TOOL_ERROR or ENVIRONMENT_ERROR → previous workflow state`; exhaustion follows the error state to `FAILED_SYSTEM`. Never claim a patch applied after tool failure. Neither failure class enters `ANALYZING_FAILURE`.

# 10. Verification failure routing

Only a successfully executed application/migration check failure may follow `VERIFYING_SANDBOX → VERIFICATION_FAILURE → ANALYZING_FAILURE`. Examples include wrong API migration, regression test failure, introduced type error, and application import failure caused by migrated code. A test runner that cannot start, missing required dependency, model failure, tool failure, or scope violation does not enter repair. Preserve the three-attempt Prompt 3 limit.

# 11. Typed data and persistence

Add or finalize `CapabilityClassification`, `GuardrailViolation`, `SystemFailureRecord`, `RetryRecord`, and `VerificationCapabilityResult`. Persist capability decisions and deterministic rules, classifier invocation/result, verification capability, violations, model/tool/environment errors and retries/recovery, failure classification, terminal reason, and every state transition in SQLite. Failed and stopped runs must be reconstructable from SQLite and exported artifacts. Controlled model responses are sufficient for automated tests; a live API key is not required.

# 12. Required state paths

- Clearly unsupported: `RECEIVED → SCOPE_CHECK → UNSUPPORTED`.
- Ambiguous supported: `SCOPE_CHECK → CAPABILITY_CLASSIFYING → VERIFICATION_CAPABILITY_CHECK → ANALYZING_REPO`.
- Ambiguous unsupported: `SCOPE_CHECK → CAPABILITY_CLASSIFYING → UNSUPPORTED`.
- Ambiguous missing information: `CAPABILITY_CLASSIFYING → NEEDS_HUMAN_REVIEW`.
- Cannot verify: `SCOPE_CHECK → VERIFICATION_CAPABILITY_CHECK → NEEDS_HUMAN_REVIEW`.
- Hard violation: `PLANNING / PATCH_GENERATING / PATCHING_SANDBOX / REPAIRING → SCOPE_VIOLATION → NEEDS_HUMAN_REVIEW`.
- Recoverable model/tool/environment error: current state to respective error state and back before retry.
- Exhausted model/tool/environment error: respective error state to `FAILED_SYSTEM`.
- Executed migration/code verification failure: `VERIFYING_SANDBOX → VERIFICATION_FAILURE → ANALYZING_FAILURE`.

# 13. Automated tests

Prove all five deterministic unsupported cases and no classifier call; ambiguous classifier supported, unsupported, and missing-information outcomes; malformed classifier rejection; insufficient verification escalation; unsafe path and weakened-test proposal rejection before patching; model retry and exhaustion; tool retry and exhaustion; environment recovery and exhaustion; environment/tool failures never reaching Failure Analyzer; only genuine verification failures entering the existing repair loop; and persisted transitions, guardrail decisions, retries, failures, and classifier telemetry. Assert intermediate states, not only terminal states. Re-run the existing Prompt 2–4 workflows.

# 14. Preserve architecture and boundaries

Keep the Prompt 2 happy path, Prompt 3 bounded repair, Prompt 4 fixed benchmark families, Context Manager budgets, independent Reviewer, repair-base and last-stable snapshots, human approval, exact patch reuse, and target-main protection. Do not add migration families, model optimization, Sol/Terra comparison, deployment, automatic merge, LangGraph, vector database, UI, or Prompt 6 functionality.

# Acceptance criteria

The Capability Gate is deterministic-first; only ambiguous semantic scope invokes a classifier; unsupported requests stop before planning; unverifiable migrations escalate; hard violations are blocked; normal migration failures remain distinct from model/tool/environment failures; typed schemas and SQLite persistence reconstruct the run; shared telemetry records classifier calls; automated Prompt 5 tests and existing Prompt 2–4 tests pass; no Prompt 6 work is added.

# Final response

Report files changed, states added, deterministic rules, classifier, unsupported cases, verification capability, scope violations, model/tool/environment handling, proof that only verification failures enter repair, persistence and telemetry, automated test results, and any blocker before Prompt 6.

## Final generic guardrail contract

Regression-test API/syntax rewrites are configured per migration family as `allowed_test_api_rewrites`. The core guardrail compares the original and proposed test syntax trees after normalizing only configured rewrites. Assertions, expected values, and business-behavior expectations must remain identical; deleted tests and unconfigured rewrites are rejected.

Before patch execution, deterministic repository analysis and migration-family configuration construct an `AllowedModificationScope`. The approved migration plan narrows the set of discovered, relevant source, test, dependency, and configuration files. Each proposed path is normalized, verified inside the repository, checked against hard prohibitions, and checked against the approved scope. Relevant files such as `requirements.txt`, `setup.cfg`, `tox.ini`, `alembic.ini`, and `celeryconfig.py` may be allowed when discovered and justified. Unrelated, secret, deployment, and traversal paths remain blocked. Prompt 3 evidence-backed scope expansion continues through deterministic approval or independent review; hard prohibitions cannot be approved. Persist the scope, per-file category and relevance reason, allowed test rewrite rule, and rejection reason in the run trace.
