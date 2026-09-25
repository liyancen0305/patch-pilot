Prompt: 06_model_optimization_eval
Version: v1
Purpose: Model quality, cost, and p95 latency evaluation and final model selection

You are implementing **Part 6 of PatchPilot: Model Optimization and Final Evaluation**.
Prompts 1–5 are complete. The PatchPilot architecture is now frozen.

Do **not** redesign the Orchestrator, state machine, Repository Analyzer, Context
Manager, sandbox, verification logic, repair loop, Change Reviewer, capability
guardrails, persistence, or benchmark cases. Determine whether cheaper/faster
models can replace the strong baseline without materially reducing system quality.

# 1. Store This Prompt

Create `docs/prompts/06_model_optimization_eval.md` with the metadata above.
Persist evaluation configuration and prompt version with every experiment.

# 2. Freeze the Evaluation Benchmark

Use the existing fixed benchmark:

* Pydantic v1 → v2
* SQLAlchemy 1.4 → 2.0
* HTTPX 0.27 → 0.28
* OpenAI Python SDK 0.28 → 1.x
* Celery 4 → 5

Do not add easier cases, remove failed cases, modify fixtures to favor a model,
change verification criteria between models, or change prompts between model
comparisons unless explicitly running a separate prompt experiment. All models
must use the same benchmark and starting state.

# 3. Identify LLM-Backed Components

Only evaluate substitution for Migration Planner, Patch Generator, Failure Analyzer,
Repair Generator, Change Reviewer, and Capability Classifier. Deterministic
components remain unchanged.

# 4. Establish the Sol Baseline

First run the complete fixed benchmark with all LLM-backed components = Sol.
Record migration family, final state, first-attempt success, total attempts, repair
success, Reviewer usage, context expansions, files changed, regressions introduced,
human escalation, model calls, input tokens, output tokens, cost, per-call latency,
and end-to-end latency. Do not begin substitution until this baseline is recorded.

# 5. Quality Metrics

Measure final migration success rate, first-pass success rate, repair success rate,
incorrect/unnecessary modification rate, regression rate, NEEDS_HUMAN_REVIEW rate,
Reviewer decision correctness where ground truth exists, and unsupported/safety
behavior preservation. Quality is primary; never select a model merely on price.

# 6. Latency Metrics

Record individual model-call latency and average and p95 latency for each
component/model combination. Use p95 to evaluate tail latency.

> If quality remains acceptably close to the Sol baseline, a cheaper model may be
> selected when its p95 latency is no more than approximately 20% slower than the
> Sol baseline and cost savings are meaningful.

A >20% slowdown requires an explicit cost/quality trade-off justification; it does
not automatically disqualify the cheaper model. Do not trade meaningful quality
loss for latency.

# 7. Cost Metrics

Use actual usage/token telemetry from live calls. Calculate cost per call,
component, migration run, average per benchmark case, and total benchmark cost.
Centralize configurable pricing and persist pricing assumptions/version. Never
fabricate cost values for test-double runs.

# 8. Model Substitution Strategy

Compare Sol against Terra. Start with all six components = Sol. Replace exactly
one component with Terra, restore baseline, and repeat for each component:
Planner, Patch Generator, Failure Analyzer, Repair Generator, Change Reviewer,
Capability Classifier. Do not initially replace multiple components simultaneously.
This makes the effect attributable to the substituted component.

# 9. Preserve Identical Workflow Semantics

Model substitution must never change the state machine. Preserve PLANNING,
PATCH_GENERATING, ANALYZING_FAILURE, AWAITING_REVIEW, REPAIRING,
NEEDS_HUMAN_REVIEW, READY_FOR_PR and all other workflow states. Model selection
must not directly control transitions; the Orchestrator remains deterministic.

# 10. Compare Each Substitution Against Baseline

For every substitution report quality difference, success-rate difference,
repair-rate difference, regression difference, human-escalation difference,
average cost difference, and p95 latency difference. Classify KEEP_SOL, USE_TERRA,
or INCONCLUSIVE and provide a concise reason, showing Sol and Terra quality,
cost, and p95 evidence.

# 11. Final Model Assignment

Choose a final model for each of the six LLM-backed components only after individual
experiments. Do not assume the outcome; every choice must have measured support.

# 12. Final Optimized End-to-End Run

Rerun the complete fixed benchmark using the chosen assignment. Confirm happy
path, Attempt 2 repair, Attempt 3 repair, max-attempt failure, Reviewer path,
context expansion, unsupported requests, scope violations, and model/tool/environment
failure routing. State semantics remain unchanged.

# 13. Evaluation Artifacts

Persist reproducible evidence under `artifacts/evaluation/`, including
`sol_baseline.json`, `component_comparisons.json`, `optimized_results.json`,
and `model_tradeoffs.md`.

# 14. README Model Selection Section

Add `Model Selection & Trade-offs`: baseline strategy, models compared, fixed
benchmark, quality/cost/p95 comparisons, final assignment, and concise trade-off
reasoning. Prefer a concise table; do not dump raw logs. Make evidence-based
model choice explicit.

# 15. Do Not Fabricate Live Evaluation

Real quality/cost/latency comparisons require real calls. If API/provider access is
unavailable: build and validate the harness, run deterministic test-double tests,
mark live evaluation `BLOCKED / NOT YET MEASURED`, invent no Sol/Terra results,
and claim no model superiority. Never silently substitute fake data.

# 16. Automated Tests

Prove the benchmark is frozen; only the selected component changes in each
experiment; deterministic architecture is unchanged; assignment is configuration
driven; metrics are consistent; p95 is correct; pricing is centralized; test-double
runs cannot be reported as live; final decisions require evidence; and the
optimized benchmark uses the selected configuration.

# Acceptance Criteria

* Sol baseline measured first; fixed benchmark unchanged.
* Terra evaluated one component at a time; quality before cost/latency.
* Actual usage cost, average/p95 latency, and ~20% default p95 guideline.
* Documented rationale for every final assignment.
* Architecture/state machine unchanged; optimized end-to-end rerun.
* Persistent artifacts and README Model Selection & Trade-offs section.
* No fabricated results; remaining limitations documented.

# Final Response

Concisely report files changed, Sol baseline results, Terra experiments by
component, quality/cost/average and p95 latency comparison, final assignment,
optimized benchmark results, artifact locations, README update, remaining
limitations, and whether provider/API access blocked live evaluation.
