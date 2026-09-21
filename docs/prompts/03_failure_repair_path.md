Prompt: 03_failure_repair_path
Version: v1
Purpose: Failure analysis, conditional review, bounded repair, context expansion, and rollback

You are implementing **Part 3 of PatchPilot: Failure Analysis and Repair**.

Prompt 2 is complete and already supports the successful happy path:

```text
Migration Request
→ Capability Check
→ Repository Analysis
→ Context Selection
→ Migration Planning
→ Patch Generation
→ Sandbox Verification
→ VERIFIED_PATCH_READY
→ Human Approval
→ Apply Exact Patch to Target Branch
→ Reverify
→ READY_FOR_PR
```

This prompt adds the workflow for **migration/code verification failures**.

Do not redesign the Prompt 2 architecture.

# 1. Store This Prompt

Create:

```text
docs/prompts/03_failure_repair_path.md
```

Store this complete prompt.

Metadata:

```text
Prompt: 03_failure_repair_path
Version: v1
Purpose: Failure analysis, conditional review, bounded repair, context expansion, and rollback
```

Runs involving this workflow must persist:

```text
prompt_name = 03_failure_repair_path
prompt_version = v1
```

# 2. Maximum 3 Total Attempts

PatchPilot may execute at most:

```text
Attempt 1 = initial migration
Attempt 2 = first repair
Attempt 3 = second repair
```

There is **no Attempt 4**.

If Attempt 3 still fails full verification:

```text
→ NEEDS_HUMAN_REVIEW
```

Persist the attempt number in SQLite.

# 3. Extend the Central State Machine

Add states equivalent to:

```text
ANALYZING_FAILURE
GATHERING_ADDITIONAL_CONTEXT
REPAIR_PROPOSED
AWAITING_REVIEW
REPAIR_APPROVED
REPAIR_REJECTED
REPAIRING
NEEDS_HUMAN_REVIEW
```

Continue using the **same central state machine** from Prompt 2.

Every transition must explicitly persist:

```text
previous_state
trigger/event
component
next_state
attempt_number
timestamp
```

Invalid transitions must be rejected.

# 4. Enter Failure Analysis

When sandbox verification fails because of migration/code correctness:

```text
VERIFYING_SANDBOX
→ ANALYZING_FAILURE
```

Persist the complete `VerificationResult`.

Do not use this path for:

```text
MODEL_ERROR
TOOL_ERROR
ENVIRONMENT_ERROR
```

Those belong to Prompt 5.

# 5. Failure Analyzer

Implement a dedicated LLM-backed `FailureAnalyzer`.

It must be a separate component/model call from:

* Migration Planner
* Patch Generator
* Change Reviewer

Provide relevant context including:

```text
migration goal
migration plan
attempt number
current diff
original relevant code
current relevant code
failing tests
expected vs actual result
stack trace
stdout/stderr
verification result
previous attempts
selected context
```

Require typed `FailureAnalysis`:

```text
failure_type
likely_root_cause
supporting_evidence
proposed_repair
files_to_modify
reason_for_each_file
additional_context_needed
confidence
```

Every proposed file modification must include:

```text
file
reason
supporting_evidence
expected_effect
required_verification
```

When valid analysis is produced:

```text
ANALYZING_FAILURE
→ REPAIR_PROPOSED
```

# 6. Progressive Context Expansion

Do not send the whole repository after failure.

Start with focused evidence such as:

```text
current diff
failing test
stack trace
directly affected source
related tests
```

If more information is needed:

```text
REPAIR_PROPOSED
→ GATHERING_ADDITIONAL_CONTEXT
```

The existing Context Manager must:

1. retrieve candidates deterministically,
2. rerank using new failure evidence,
3. respect `max_files`,
4. respect `max_snippets`,
5. respect `max_context_tokens`,
6. add only justified context.

Ranking signals can include:

```text
appears in stack trace
modified by current patch
caller/callee relationship
import relationship
inheritance relationship
shared configuration
related failing test
migration API usage
```

Persist:

```text
previous context
new context
selection/ranking reason
expansion reason
context size
token estimate
```

Then:

```text
GATHERING_ADDITIONAL_CONTEXT
→ ANALYZING_FAILURE
```

Do not simply keep appending context indefinitely.

# 7. Repair Decision — Two Paths

Every proposed repair must take one of two paths.

## Case A — Clear and Deterministically Justified

The Orchestrator may authorize directly when objective evidence shows:

```text
requested file exists
file is clearly related to migration/failure
change remains in supported scope
evidence directly supports the modification
action is not destructive/prohibited
scope expansion is not ambiguous
```

Transition:

```text
REPAIR_PROPOSED
→ REPAIR_APPROVED
```

Persist why deterministic approval was allowed.

The Orchestrator must not perform complex semantic code reasoning.

## Case B — Unclear / Risky / Scope-Expanding

Use an AI Change Reviewer when:

```text
new file outside original plan is requested
scope expands
shared/base infrastructure is affected
evidence is ambiguous
Orchestrator cannot deterministically justify the change
regression risk is elevated
```

Transition:

```text
REPAIR_PROPOSED
→ AWAITING_REVIEW
```

# 8. Independent Change Reviewer

The Reviewer must be:

```text
separate model call
separate prompt/role
separate typed output
independent from Failure Analyzer
```

The Failure Analyzer must never approve its own repair proposal.

Reviewer input:

```text
migration goal
original migration plan
attempt number
current failure
current diff
relevant code
proposed repair
requested files
supporting evidence
verification result
```

Require typed `ReviewDecision`:

```text
decision:
  APPROVE
  REJECT
  NEED_MORE_EVIDENCE

reason
supporting_evidence
risk
additional_context_needed
required_verification
```

### APPROVE

```text
AWAITING_REVIEW
→ REPAIR_APPROVED
```

### NEED_MORE_EVIDENCE

```text
AWAITING_REVIEW
→ GATHERING_ADDITIONAL_CONTEXT
```

Context Manager retrieves/reranks context, then Reviewer reevaluates.

### REJECT

```text
AWAITING_REVIEW
→ REPAIR_REJECTED
```

If another evidence-supported strategy exists and attempts remain:

```text
REPAIR_REJECTED
→ ANALYZING_FAILURE
```

Otherwise:

```text
REPAIR_REJECTED
→ NEEDS_HUMAN_REVIEW
```

# 9. Stable Snapshot Rule

Before every repair, record both the current **last verified stable snapshot** and the **repair base checkpoint** at sandbox HEAD.

Required behavior:

```text
repair base checkpoint
→ apply repair
→ candidate checkpoint
→ verify
```

If full verification succeeds:

```text
candidate checkpoint
→ promoted to stable
```

If verification fails:

```text
previous stable snapshot remains stable
```

An unverified repair must never become stable.

Persist:

```text
last_verified_stable_snapshot_id
repair_base_checkpoint_id
candidate_checkpoint_id
repair_diff
verification_before
verification_after
rollback_target
rollback_reason
rollback_result
```

# 10. Repair Execution

When:

```text
state = REPAIR_APPROVED
```

transition:

```text
REPAIR_APPROVED
→ REPAIRING
```

The repair model may generate a patch, but deterministic code must:

```text
validate paths
enforce approved file scope
reject unauthorized files
prevent path traversal
apply only inside sandbox
capture Git diff
create candidate checkpoint
```

After application:

```text
REPAIRING
→ VERIFYING_SANDBOX
```

Do not modify the target repository during repair attempts.

# 11. Verification After Repair

When useful, first run the directly affected test.

If it passes, run the complete verification suite:

```text
migration-specific checks
regression tests
pytest
mypy
ruff
runtime/import sanity check
```

A targeted test passing is never enough.

## If full verification passes

```text
VERIFYING_SANDBOX
→ VERIFIED_PATCH_READY
```

Promote candidate checkpoint to stable.

Then rejoin Prompt 2:

```text
VERIFIED_PATCH_READY
→ AWAITING_APPROVAL
→ APPROVED
→ APPLYING_TO_TARGET_BRANCH
→ VERIFYING_TARGET_BRANCH
→ READY_FOR_PR
```

## If full verification fails and attempts remain

Increment the attempt count and transition:

```text
VERIFYING_SANDBOX
→ ANALYZING_FAILURE
```

Use the **new failure evidence**, not only the previous failure.

# 12. Required Attempt Paths

## Path A

```text
Attempt 1 FAIL
→ Failure Analysis
→ Repair
→ Attempt 2 PASS
→ normal Prompt 2 happy path
```

## Path B

```text
Attempt 1 FAIL
→ Attempt 2 FAIL
→ new Failure Analysis
→ Attempt 3 PASS
→ normal Prompt 2 happy path
```

## Path C

```text
Attempt 1 FAIL
→ Attempt 2 FAIL
→ Attempt 3 FAIL
→ NEEDS_HUMAN_REVIEW
```

No fourth attempt is allowed.

# 13. Detect Degraded Repairs

Compare verification before and after every repair.

Treat a repair as degraded when, for example:

```text
new unrelated regression failures appear
failing-test count materially increases
previously passing checks now fail
unexpected unrelated files are modified
```

When degraded:

1. reject candidate repair,
2. rollback to the current repair_base_checkpoint,
3. persist the reason.

If attempts remain:

```text
→ ANALYZING_FAILURE
```

Otherwise:

```text
→ NEEDS_HUMAN_REVIEW
```

# 14. Scope Expansion

AI may request permission to modify a new file.

AI may not authorize the expansion itself.

Every request must include:

```text
requested_file
reason
supporting_evidence
expected_effect
required_verification
```

If objective evidence clearly supports it:

```text
Orchestrator → REPAIR_APPROVED
```

If ambiguous:

```text
→ AWAITING_REVIEW
```

# 15. Preserve Regression-Test Guardrails

Repair patches must not:

```text
delete failing tests
weaken assertions
change expected values merely to pass
change business-behavior expectations merely to pass
```

Migration-required test syntax/API updates are allowed only when behavior remains equivalent and justification is explicit.

# 16. Typed Schemas

Add typed schemas for at least:

```text
FailureAnalysis
RepairProposal / PatchProposal
ReviewDecision
RepairAttemptRecord
ContextExpansionRecord
```

All LLM outputs must be schema validated.

Malformed output must not enter the workflow.

# 17. Persistence

Extend SQLite persistence for:

```text
attempt_number
FailureAnalysis
repair-decision path
deterministic approval reason
Reviewer invocation/result
context-expansion history
stable snapshot
candidate checkpoint
repair diff metadata
verification before/after
rollback events
final status
```

A run must be reconstructable later.

# 18. Model Telemetry

Continue using the shared model-client/telemetry layer.

Record calls for:

```text
Failure Analyzer
Repair Generator
Change Reviewer
```

Persist:

```text
model
component
prompt/version
tokens if available
latency
estimated cost if available
structured output
errors
attempt number
```

For automated testing, use controlled/fake model outputs.

**Live Sol execution remains deferred until the later model-evaluation phase.**

Do not require an OpenAI API key to close Prompt 3.

# 19. Required Automated Tests

Cover at minimum:

```text
[ ] Attempt 1 fails
    → clear repair
    → Attempt 2 succeeds

[ ] Attempt 1 fails
    → ambiguous repair
    → Reviewer APPROVE
    → Attempt 2 succeeds

[ ] Reviewer NEED_MORE_EVIDENCE
    → Context Manager expands/reranks
    → Reviewer reevaluates

[ ] Reviewer REJECT
    → repair is not applied

[ ] Attempt 1 fails
    → Attempt 2 fails
    → Attempt 3 succeeds

[ ] Attempt 1 fails
    → Attempt 2 fails
    → Attempt 3 fails
    → NEEDS_HUMAN_REVIEW

[ ] Attempt 4 is impossible

[ ] unverified repair never becomes stable

[ ] successful repair promotes candidate to stable

[ ] degraded repair rolls back to the current repair_base_checkpoint

[ ] new-file scope expansion requires justification

[ ] clear scope expansion can be deterministically approved

[ ] ambiguous scope expansion invokes Reviewer

[ ] regression assertions cannot be weakened

[ ] context expansion respects all budgets

[ ] Failure Analyzer and Reviewer are independent model calls

[ ] repair/context/reviewer/state history is persisted
```

# 20. Explicit State Assertions

Tests must validate intermediate state transitions, not only final outcomes.

Example direct path:

```text
VERIFYING_SANDBOX
→ ANALYZING_FAILURE
→ REPAIR_PROPOSED
→ REPAIR_APPROVED
→ REPAIRING
→ VERIFYING_SANDBOX
→ VERIFIED_PATCH_READY
```

Example Reviewer path:

```text
REPAIR_PROPOSED
→ AWAITING_REVIEW
→ GATHERING_ADDITIONAL_CONTEXT
→ AWAITING_REVIEW
→ REPAIR_APPROVED
→ REPAIRING
```

Max-attempt path:

```text
Attempt 3 verification failure
→ NEEDS_HUMAN_REVIEW
```

# Boundaries

Do NOT implement:

* Prompt 4 additional migration families
* Prompt 5 unsupported/system failure suite
* model optimization
* Terra substitution
* Sol-vs-Terra comparison
* automatic PR creation
* automatic merge
* production deployment
* LangGraph
* vector database
* UI

# Acceptance Criteria

Before finishing:

```text
[ ] Failure Analyzer is implemented as a distinct component

[ ] Reviewer is an independent model call

[ ] total attempts are capped at exactly 3

[ ] every failure/repair state change is explicit

[ ] direct deterministic approval and Reviewer approval are separate paths

[ ] progressive Context Manager expansion works

[ ] context ranking/budgets remain enforced

[ ] repair happens only inside sandbox

[ ] unverified repairs never become stable

[ ] degraded repair rollback restores its repair_base_checkpoint without promoting it to stable

[ ] degraded repairs can be rejected/rolled back

[ ] complete verification is required after repair

[ ] successful repair rejoins Prompt 2 happy path

[ ] Attempt 3 failure reaches NEEDS_HUMAN_REVIEW

[ ] no Attempt 4 exists

[ ] repair/reviewer/context/state history is persisted

[ ] automated Prompt 3 failure-path tests pass

[ ] no OpenAI API key is required for Prompt 3 acceptance

[ ] no Prompt 4–6 functionality was implemented
```

# Final Response

Report concisely:

1. files changed
2. states added
3. schemas added
4. Failure Analyzer implementation
5. direct repair-approval logic
6. Reviewer implementation
7. Context Manager expansion behavior
8. stable snapshot / rollback behavior
9. Attempt 1→2 test result
10. Attempt 1→2→3 test result
11. max-attempt failure result
12. persistence/telemetry added
13. complete automated test results
14. any blocker before Prompt 4


# Prompt 3 final clarification: repair base and context exhaustion

For each repair attempt, persist both `last_verified_stable_snapshot_id` and
`repair_base_checkpoint_id`. The stable snapshot is the most recent candidate
that passed the full verification suite. The repair base is the sandbox
checkpoint at which that repair began, even when its verification failed.
A degraded repair rolls back to its repair base. Attempt 2 therefore restores
the Attempt 1 migration candidate after degradation; Attempt 3 starts from the
Attempt 2 candidate when Attempt 2 failed without degradation. Rollback must
not promote the repair base to stable. Persist `rollback_target`,
`rollback_reason`, and `rollback_result`.

Use one configurable context-expansion limit across Failure Analyzer and
Reviewer requests. Persist `expansion_count` and `expansion_limit`. When
the Failure Analyzer still requests evidence after the limit, transition
`ANALYZING_FAILURE → NEEDS_HUMAN_REVIEW`. When the Reviewer returns
`NEED_MORE_EVIDENCE` after the limit, transition
`AWAITING_REVIEW → NEEDS_HUMAN_REVIEW`. Persist
`unresolved_context_request` and `reason_for_escalation`. Neither path
may approve or execute a repair while required evidence remains unresolved.
