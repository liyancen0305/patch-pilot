Prompt: 02_happy_path_e2e
Version: v1.1
Purpose: First complete PatchPilot happy-path migration workflow

You are implementing **Part 2 of PatchPilot: the first complete happy-path migration workflow**.

Part 1 already provides:

* a canonical Pydantic v1 fixture repository
* baseline regression tests
* `pytest`, `mypy`, `ruff`, and runtime/import verification
* deterministic repository tools
* sandbox / isolated working-copy support
* Git snapshots, diffs, checkpoints, and rollback
* SQLite/storage foundation
* prompt storage under `docs/prompts/`

Do not implement the failure-repair workflow yet. That belongs to Prompt 3.

# Goal

Given a valid request:

> Upgrade the fixture application from Pydantic v1 to Pydantic v2 while preserving existing behavior.

PatchPilot must complete this end-to-end happy path:

```text
Migration Request
→ Capability Check
→ Repository Analysis
→ Context Selection
→ Migration Planning
→ Patch Generation
→ Apply Patch in Sandbox
→ Verify Sandbox
→ VERIFIED_PATCH_READY
→ Simulated Human Approval
→ Apply Exact Verified Patch to Target Branch
→ Re-run Verification
→ READY_FOR_PR
```

The canonical benchmark fixture must never be permanently modified.

---

# 1. Store This Prompt

Create:

```text
docs/prompts/02_happy_path_e2e.md
```

Store the **full final Prompt 2 text**, not a summary.

Include metadata:

```text
Prompt: 02_happy_path_e2e
Version: v1.1
Purpose: First complete PatchPilot happy-path migration workflow
```

Every run created by this prompt must persist:

```text
prompt_name = 02_happy_path_e2e
prompt_version = v1.1
```

---

# 2. Implement One Central State Machine

Implement a single authoritative workflow state model.

Do not scatter state logic throughout components.

Use explicit states equivalent to:

```text
RECEIVED
SCOPE_CHECK
ANALYZING_REPO
CONTEXT_BUILDING
PLANNING
PATCH_GENERATING
PATCHING_SANDBOX
VERIFYING_SANDBOX
VERIFIED_PATCH_READY
AWAITING_APPROVAL
APPROVED
APPLYING_TO_TARGET_BRANCH
VERIFYING_TARGET_BRANCH
READY_FOR_PR
MODEL_ERROR
TOOL_ERROR
ENVIRONMENT_ERROR
FAILED_SYSTEM
```

Implement:

* typed state enum
* explicit allowed-transition table
* transition function
* rejection of invalid transitions
* persisted state history

Every state-changing action must record:

```text
previous_state
trigger/event
component
next_state
timestamp
```

State transitions must never be implicit.

---

# 3. Required Happy-Path State Transitions

## Request

When a valid migration request is created:

```text
INITIAL → RECEIVED
```

When Orchestrator begins capability evaluation:

```text
RECEIVED → SCOPE_CHECK
```

## Capability Check

If Capability Gate returns `SUPPORTED`:

```text
SCOPE_CHECK → ANALYZING_REPO
```

Do not implement the full unsupported-request suite yet.

## Repository Analysis

When Repository Analyzer successfully completes:

```text
ANALYZING_REPO → CONTEXT_BUILDING
```

## Context Selection

When Context Manager produces a valid ContextBundle:

```text
CONTEXT_BUILDING → PLANNING
```

## Planning

When Migration Planner returns a valid structured MigrationPlan:

```text
PLANNING → PATCH_GENERATING
```

## Patch Generation

When a valid PatchProposal is generated:

```text
PATCH_GENERATING → PATCHING_SANDBOX
```

## Sandbox Patch

When the patch is successfully applied inside the sandbox:

```text
PATCHING_SANDBOX → VERIFYING_SANDBOX
```

## Sandbox Verification

If all required verification checks pass:

```text
VERIFYING_SANDBOX → VERIFIED_PATCH_READY
```

If verification fails:

* persist the failure result
* stop this Prompt 2 workflow
* do not attempt repair yet

Prompt 3 will add:

```text
VERIFYING_SANDBOX → ANALYZING_FAILURE
```

## Human Approval

When sandbox verification has succeeded:

```text
VERIFIED_PATCH_READY → AWAITING_APPROVAL
```

When simulated human approval returns `APPROVE`:

```text
AWAITING_APPROVAL → APPROVED
```

## Target Branch Application

When Orchestrator authorizes applying the verified patch:

```text
APPROVED → APPLYING_TO_TARGET_BRANCH
```

After the exact verified patch has been applied:

```text
APPLYING_TO_TARGET_BRANCH → VERIFYING_TARGET_BRANCH
```

## Final Verification

If all target-branch verification checks pass:

```text
VERIFYING_TARGET_BRANCH → READY_FOR_PR
```

`READY_FOR_PR` is the successful terminal state for Prompt 2.

---

# 4. Implement Typed Data Contracts

Create one consistent typed schema layer for workflow data.

At minimum implement structured types equivalent to:

```text
MigrationRequest
CapabilityDecision
RepositoryAnalysis
ContextItem
ContextBundle
MigrationPlan
PlannedChange
PatchProposal
PatchResult
VerificationCheck
VerificationResult
ApprovalDecision
RunRecord
ModelCallRecord
StateTransitionRecord
```

LLM outputs must be parsed and validated against their schemas.

Do not allow the Orchestrator to infer meaning from malformed free-form text.

If required structured output is invalid after the configured retry policy:

```text
current AI state → MODEL_ERROR
```

---

# 5. Persistence

Implement real durable workflow persistence using the existing SQLite foundation.

Persist at minimum:

```text
run_id
migration_request
current_state
state_history
prompt_name/version
repository identifiers
repository analysis
selected context metadata
migration plan
patch metadata
verification results
approval decision
model-call telemetry
final_status
start/end timestamps
```

Use:

```text
SQLite → workflow/run metadata
Git/filesystem → code snapshots, diffs, branches, and artifacts
```

Do not store entire repository snapshots in SQLite.

The system should be able to reconstruct what happened during a completed run.

---

# 6. Migration Request

Create a structured request for:

```text
Pydantic v1 → Pydantic v2
```

Include:

```text
repository
migration_goal
constraints
```

Constraints should include:

```text
remain in Python
preserve existing behavior
do not modify unrelated files
do not deploy automatically
do not merge automatically
```

---

# 7. Canonical Fixture vs Target Repository

Maintain three distinct concepts:

### Canonical Fixture

The immutable benchmark starting point created in Prompt 1.

It must remain unchanged.

### Target Repository

Create a target repository derived from the canonical fixture.

This simulates the user's real repository.

### Sandbox

Create an isolated working copy from the target repository.

All AI-generated migration changes must first be applied only inside the sandbox.

---

# 8. Capability Gate

For this supported happy path, use deterministic checks to verify:

```text
language == Python
migration is same-language
migration type is supported
verification commands exist in the configured verification Python/environment, including when it differs from PatchPilot's runtime
sandbox isolation is available
target branch operations are available
```

Return a typed `CapabilityDecision`.

Do not use an LLM when deterministic rules already establish support.

The ambiguous semantic-classification fallback will be expanded in Prompt 5.

---

# 9. Repository Analyzer

Repository analysis must be primarily deterministic.

At minimum use the Part 1 primitives to inspect:

* dependency files
* current Pydantic version
* Python source files
* test files
* configuration files
* imports
* classes
* inheritance
* decorators
* Pydantic-specific API usages
* likely related tests

Use:

```text
filesystem
ripgrep
Python AST
dependency/config parsing
test discovery
import/reference relationships
```

The analyzer must actually invoke the Part 1 `rg` search primitive for migration API and symbol references; an unused search helper does not satisfy this requirement. Combine its line evidence with filesystem discovery, Python AST, dependency/config parsing, test discovery, and import/reference relationships. Persist evidence explaining how candidate affected files and related tests were found.

Produce typed `RepositoryAnalysis`.

Do not simply ask the LLM to inspect the whole repository.

---

# 10. Context Manager — Ranking and Budget

Implement deterministic **snippet-level** context selection. Identify migration-relevant symbols and sections within files, then rank the snippets rather than treating every candidate as a whole file.

## Candidate Retrieval

Retrieve context candidates using evidence such as:

```text
direct Pydantic imports
v1-specific API usage
inheritance relationships
related tests
configuration relationships
symbol references
```

## Ranking

Assign deterministic relevance priority/score.

Higher relevance should be given to evidence such as:

```text
direct migrated API usage
direct dependency import
shared/base class relationship
test directly exercising affected code
configuration affecting affected models
```

Persist each selected snippet's file, location/symbol, ranking reason, relevance score, and estimated token size. Relevant API, model, dependency, and related-test snippets must rank above unrelated material.

## Context Budget

Introduce configurable limits such as:

```text
max_files
max_snippets
max_context_tokens
```

Do not automatically send the full repository.

Enforce `max_files`, `max_snippets`, and `max_context_tokens` independently. Select the highest-ranked snippets that fit all three budgets; `max_snippets` must not act as another name for `max_files`.

Produce a typed `ContextBundle`.

Persist:

```text
selected files/snippets
ranking/relevance reason
context size
context token estimate
```

Repair-time progressive expansion belongs to Prompt 3.

---

# 11. Baseline Model Interface

Use **Sol** as the baseline model for all LLM-backed steps in Prompt 2.

LLM-backed steps are:

```text
Migration Planner
Patch Generator
```

Keep all model access behind one reusable model-client abstraction so models can later be substituted without changing workflow logic.

Do not implement Sol-vs-Terra comparison yet.

---

# 12. Unified Model Telemetry

Every model call must go through the shared model-client/telemetry layer.

Record:

```text
run_id
component
model
prompt_name
prompt_version
input/context metadata
input tokens
output tokens
latency
estimated cost
structured output
error if any
timestamp
```

Do not rely only on console logs.

Persist telemetry in SQLite.

---

# 13. Migration Planner

Provide the model:

```text
MigrationRequest
ContextBundle
RepositoryAnalysis summary
```

Require structured `MigrationPlan` containing:

```text
summary
planned_changes
affected files
reason for each change
risks
validation plan
```

Each planned change must explain:

```text
file
symbol/location if known
why the change is required
intended migration change
expected effect
```

The planner must not perform unrelated refactoring.

Planning and patch generation must remain separate steps.

---

# 14. Patch Generation

Provide:

```text
MigrationPlan
relevant ContextBundle
required constraints
```

Require a structured `PatchProposal`.

The model proposes the patch but must not directly mutate:

```text
canonical fixture
target repository
target branch
```

Deterministic code validates the proposal before applying it. Test-file edits are allowed only for required migration syntax/API compatibility. Reject proposals that weaken assertions, expected values, or business-behavior expectations to obtain a passing test result.

---

# 15. Apply Patch Only to Sandbox

Before applying the patch:

* record the current stable snapshot
* validate referenced paths
* ensure files are inside the sandbox
* reject path traversal/out-of-repository writes

Then:

```text
apply proposed patch
capture Git diff
record changed files
create a candidate checkpoint without updating `last_stable_snapshot`
```

The canonical fixture and target repository remain unchanged.

Persist:

```text
pre-patch stable snapshot
post-patch candidate checkpoint
changed files
diff
```

---

# 16. Sandbox Verification

Run deterministic verification.

At minimum:

```text
migration-specific Pydantic v2 checks
existing regression tests
pytest
mypy
ruff
runtime/import sanity check
```

Also verify that targeted Pydantic v1 usages have been migrated where required.

The LLM must never decide whether the migration passed.

`VerificationRunner` determines success from commands/results/exit codes.

If all checks pass, promote the candidate checkpoint to the last stable snapshot, then transition:

```text
VERIFYING_SANDBOX → VERIFIED_PATCH_READY
```

If any required check fails:

* persist `VerificationResult`
* leave `last_stable_snapshot` pointing to the previous verified state
* confirm rollback restores that previous verified state
* stop Prompt 2
* do not repair yet

---

# 17. Simulated Human Approval

After reaching:

```text
VERIFIED_PATCH_READY
```

transition to:

```text
AWAITING_APPROVAL
```

Implement an explicit simulated human-approval input.

For this happy-path test, provide:

```text
APPROVE
```

Then:

```text
AWAITING_APPROVAL → APPROVED
```

The approval gate must not be silently bypassed.

Persist the approval decision.

---

# 18. Apply Exact Verified Patch to Target Branch

After approval:

1. create a new branch in the target repository,
2. apply the **exact patch already verified in the sandbox**,
3. do not regenerate code,
4. do not invoke the model for new modifications,
5. record the target main/default-branch commit before application and confirm it is unchanged afterward.

Record:

```text
target branch
verified patch identifier/hash
applied diff
commit/snapshot
```

The applied target-branch diff must match the sandbox-verified diff exactly. Only the new migration branch may contain the verified patch.

---

# 19. Re-verify Target Branch

Run the same complete verification suite again on the target branch:

```text
migration-specific checks
regression tests
pytest
mypy
ruff
runtime/import sanity
```

If all pass:

```text
VERIFYING_TARGET_BRANCH → READY_FOR_PR
```

Do not automatically create or merge a PR.

`READY_FOR_PR` means the branch is ready for human code review / PR creation.

---

# 20. Observability / Run Reconstruction

At the end of a run, it must be possible to reconstruct:

```text
request
every state transition
repository analysis
context selected and why
model calls
migration plan
sandbox patch
sandbox verification
human approval
target branch
target verification
cost
latency
final state
```

The system must not depend on console output alone for this information.

---

# 21. Tests

Add tests covering at minimum:

### State machine

* valid happy-path transitions succeed
* invalid transitions are rejected
* state history is persisted

### Schemas

* valid model outputs parse successfully
* malformed required structured output is rejected

### Persistence

* run survives being reloaded from SQLite
* current state/history can be reconstructed
* telemetry records can be retrieved

### Repo Analyzer

* identifies Pydantic dependency/version
* identifies relevant source files
* identifies important v1 usages
* identifies related tests

### Context Manager

* relevant files rank above unrelated files
* file, snippet, and token budgets are enforced independently
* relevant snippets rank above unrelated snippets
* selection locations, scores, reasons, and token estimates are persisted

### Sandbox

* target/canonical repositories remain unchanged during sandbox modification
* applying an AI patch creates a candidate without advancing `last_stable_snapshot`
* successful verification promotes the candidate; failed verification does not
* rollback after failed verification restores the previous verified stable state
* behavioral regression-test edits are rejected

### Happy path

A complete run reaches:

```text
READY_FOR_PR
```

only after:

```text
sandbox verification
human approval
target-branch application
target-branch re-verification
```

Record the target main/default-branch commit before application and assert that it is unchanged after `READY_FOR_PR`.

Run one complete controlled-model end-to-end test through the real Orchestrator, sandbox, SQLite persistence, approval gate, target branch, and a real isolated Pydantic v2 verification environment. Only the model responses may be deterministic test doubles; they must be schema-valid `MigrationPlan` and `PatchProposal`. Persist model identity as a test double, structured outputs, state history, both real verification results, approval, and target branch. The run must reach `READY_FOR_PR` and must not be skipped because an OpenAI API key is absent.

---

# 22. Boundaries

Do NOT implement yet:

* Failure Analyzer
* repair loop
* progressive context expansion after failure
* AI Change Reviewer
* max-3-attempt repair logic
* rollback-based repair strategy
* unsupported-use-case suite
* model comparison
* Terra substitution
* automatic PR creation
* automatic merge
* production deployment
* LangGraph
* vector database
* UI

Do not implement Prompt 3 functionality early.

---

# Acceptance Criteria

Before finishing, verify all of the following:

```text
[ ] Full final Prompt 2 v1.1 is stored in docs/prompts/02_happy_path_e2e.md

[ ] Every new run persists prompt_name = 02_happy_path_e2e and prompt_version = v1.1

[ ] One central state machine exists

[ ] Allowed transitions are explicitly enforced

[ ] Every state change records trigger/component/current/next state

[ ] Typed workflow schemas exist

[ ] LLM outputs are schema validated

[ ] SQLite persists run state/history and workflow metadata

[ ] Git/filesystem persists code snapshots/diffs

[ ] Repository Analyzer actually uses rg, AST, dependency/config parsing, test discovery, and reference/import analysis, with evidence

[ ] Context Manager ranks located snippets deterministically above unrelated snippets

[ ] Context Manager independently enforces max_files, max_snippets, and max_context_tokens

[ ] Context selection reason/history is persisted

[ ] Sol is used as the baseline model

[ ] All model calls use unified telemetry

[ ] Migration Planner returns structured plan

[ ] Patch Generator returns structured proposal

[ ] Patch is first applied only inside sandbox as a candidate checkpoint

[ ] Unverified or failed patches never become last_stable_snapshot; rollback restores the prior verified state

[ ] Regression assertions and expected values cannot be weakened merely to pass verification

[ ] Canonical fixture remains unchanged

[ ] Target repository remains unchanged before approval

[ ] Sandbox verification passes

[ ] Status becomes VERIFIED_PATCH_READY only after sandbox verification passes

[ ] Human approval is explicitly simulated

[ ] Exact verified patch is applied to a new target branch

[ ] Target main/default branch commit remains unchanged before and after application

[ ] Target branch is fully reverified

[ ] Final state becomes READY_FOR_PR only after target verification passes

[ ] A complete controlled-model run with schema-valid plan and proposal, durable telemetry, and real Pydantic v2 verification reaches READY_FOR_PR

[ ] No repair/Reviewer/model-optimization functionality was implemented
```

# Final Response

At completion, report concisely:

1. files created or changed
2. central state machine and implemented transitions
3. schemas implemented
4. SQLite persistence implemented
5. Repository Analyzer findings
6. selected context and ranking reasons
7. context budget used
8. MigrationPlan produced
9. sandbox patch/diff
10. sandbox verification results
11. simulated approval result
12. target branch created
13. confirmation that the exact verified patch was reused
14. target-branch verification results
15. final `READY_FOR_PR` state
16. model/token/cost/latency telemetry
17. confirmation that canonical fixture and target main/default branch remained unchanged

Prompt 2 completion requires the controlled-model end-to-end run, including real sandbox and target verification, to reach `READY_FOR_PR`. An OpenAI API key is not required for this acceptance test.


## Final Structured Outputs and Evidence Requirement

For every Sol-backed Migration Planner and Patch Generator call, use the OpenAI Responses API native strict JSON Schema Structured Outputs feature. Derive the API schema from the corresponding Pydantic `MigrationPlan` or `PatchProposal` contract, then perform local Pydantic validation as a second layer. Invalid output follows the existing `MODEL_ERROR` transition; never manually repair it. Keep all calls behind the shared model client and preserve per-call telemetry.

Persist each run under a stable project artifact path such as `artifacts/<run-root>/runs/<run_id>/` with its SQLite record, state history, selected context, structured plan and proposal, model telemetry, verification outcomes, explicit approval, target branch diff, exact verified patch and SHA-256, and a concise machine-readable summary. Reuse the exact sandbox-verified patch on the target branch. A Prompt 2 closeout requires a complete controlled-model run in a real Pydantic v2 verifier to reach `READY_FOR_PR`; a skipped or blocked run is not a successful acceptance test.


## Live Sol validation

**DEFERRED / optional until the model evaluation and optimization phase.** Prompt 2 validates complete orchestration with a controlled model test double. Real Sol model quality, cost, and latency will be evaluated later. Keep the shared Sol backend, native Structured Outputs, Pydantic validation, and telemetry infrastructure available; live API access is not a Prompt 2 acceptance requirement.
