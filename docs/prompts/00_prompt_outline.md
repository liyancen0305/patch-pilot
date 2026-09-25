# PatchPilot prompt outline

The six prompts record the project's engineering stages. They are historical
implementation specifications; [the README](../../README.md) describes the current
portfolio deliverable. Prompt 6 delivered an evaluation **framework**; live model
benchmarking is **NOT MEASURED / DEFERRED** and is not required to run the project.

1. **[Prompt 1 — Environment + Fixture Foundation](01_environment_fixture.md)** · v1  
   Establish a reproducible Python fixture, repository tools, isolated Git sandbox,
   and verification commands. The main concern is preserving an immutable starting
   repository while keeping every candidate change reversible.
2. **[Prompt 2 — Happy Path End-to-End](02_happy_path_e2e.md)** · v1.1  
   Connect analysis, bounded context, planning, patch generation, sandbox checks,
   approval, target-branch application, and final verification. Schema validation
   and deterministic state transitions keep model proposals from becoming unchecked edits.
3. **[Prompt 3 — Failure Analysis + Repair](03_failure_repair_path.md)** · v1  
   Add evidence-based failure analysis, conditional independent review, context
   expansion, and at most two repairs after the initial patch. Checkpoints and
   rollback prevent a degraded repair from silently becoming the new baseline.
4. **[Prompt 4 — Generalization Across Migration Families](04_remaining_use_cases.md)** · v1.1  
   Exercise the same workflow across five fixed Python dependency/API migrations.
   Family metadata replaces Pydantic-specific core decisions; controlled faults test
   repair and escalation with real verification tools.
5. **[Prompt 5 — Guardrails + System Failures](05_guardrails_failures.md)** · v1  
   Enforce supported scope, constrain edits, and route model, tool, environment,
   and persistence failures. The key distinction is between broken migrated code
   that may justify repair and infrastructure failures that do not.
6. **[Prompt 6 — Model Evaluation Framework](06_model_optimization_eval.md)** · v1  
   Freeze evaluation inputs, establish a baseline-first experiment sequence, and
   substitute Sol/Terra one component at a time. Evidence gates prioritize quality
   before cost and p95 latency; controlled tests validate the framework without
   claiming live model measurements or selecting a winner.
