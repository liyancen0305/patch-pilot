# Interview talking points

These answers describe the implemented MVP. Results are **CONTROLLED / TEST-DOUBLE
EVALUATION**; live model quality, cost, and latency are **NOT MEASURED / DEFERRED**.

**What problem does PatchPilot solve?**  
Dependency upgrades often change behavior beyond syntax. PatchPilot gives a narrow
migration an explicit plan, isolated execution, verification, bounded repair, and
an audit trail before a target branch is prepared for review.

**How is it different from a normal coding agent?**  
It is a constrained migration workflow rather than an open-ended coding assistant.
A deterministic state machine controls which action is legal, what files may change,
how much context is selected, and when to stop.

**Why not let the LLM directly edit the repository?**  
A plausible patch can be wrong or out of scope. Models return schema-validated
proposals; deterministic policy checks them, applies them in a Git sandbox, and
verifies them before approved target-branch changes.

**What does the Orchestrator control?**  
State transitions, capability checks, tool/model invocation, repair authorization,
review routing, retry/attempt budgets, approval, rollback, escalation, and persistence.
Neither a model's prose nor the selected model ID can directly advance the state.

**Why is Context Manager deterministic?**  
Reproducible evidence selection makes behavior easier to inspect and compare.
Repository relationships and explicit ranking rules govern selection; a model may
request more evidence but cannot override context limits.

**Why use context ranking and budgets?**  
The full repository is usually unnecessary, noisy, and expensive to send. File,
snippet, and estimated-token budgets prioritize relevant APIs, tests, and dependencies
while leaving a bounded route for progressive evidence expansion.

**What happens after the first patch fails?**  
The Failure Analyzer receives verification evidence, the current diff, plan, prior
attempts, and context. A permitted repair is approved by deterministic policy or
reviewed independently, applied in the sandbox, and checked again. Only two repair
attempts are available after the initial migration.

**Why use an independent Reviewer?**  
An ambiguous repair deserves a separate assessment of scope and evidence instead
of the proposing model approving itself. The Reviewer can reject or request evidence,
but approval cannot bypass hard guardrails or deterministic verification. It is an
independent invocation/role, not a guarantee of statistical independence or correctness.

**Why only three attempts?**  
The limit makes cost and execution bounded and prevents a repair loop from drifting
indefinitely. Attempt 1 migrates; Attempts 2 and 3 repair. Continued failure requires
human review rather than an unbounded fourth attempt.

**How does rollback work?**  
Each repair records a pre-repair candidate checkpoint. If checks degrade, rollback
restores `repair_base_checkpoint`, which may still be a failing migration candidate.
That is different from `last_verified_stable`, which represents verified code and is
advanced only after verification passes.

**How do you distinguish migration failure from system failure?**  
A completed check exposing bad migrated behavior can justify code repair. An invalid
model response, tool failure, missing verification environment, or persistence error
uses a separate recovery/failure route; it is not evidence to change application code.

**How did you test generalization beyond Pydantic?**  
The same workflow runs fixed SQLAlchemy, HTTPX, OpenAI SDK, and Celery fixtures using
family metadata. Persisted controlled runs cover happy paths, repairs on Attempts 2
and 3, review/evidence expansion, and intentional max-attempt escalation. This proves
workflow integration with real verifiers, not model competence on arbitrary repositories.

**How would you evaluate model quality/cost/latency in production?**  
Freeze tasks, initial repositories, prompts, verification, and environment versions;
record a strong-model baseline; then substitute one component at a time. Assess
success, regressions, scope/safety behavior, and independently labeled review decisions
before measuring actual token-based cost and component p95 latency. Use larger,
representative samples and explicit uncertainty; rerun the final mixed assignment.
The implemented 20% p95 guideline is a portfolio rule, not a production SLA. No
live Sol/Terra measurements or evidence-based winner are claimed here.

**What would you add for a production version?**  
Hardened execution isolation, authenticated approvals, secret-safe audit retention,
reproducible dependency environments, larger representative evaluation with independent
labels, observability, and operational access controls. These are future work, not
features of the MVP; production deployment and merging would remain explicitly governed.
