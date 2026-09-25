# PatchPilot

A Python dependency/API migration prototype that treats AI-generated changes as
proposals and promotes them only through explicit workflow controls and verification.
The reproducible portfolio demo uses **CONTROLLED / TEST-DOUBLE EVALUATION** with
real repository tools, Git sandboxes, and verification commands. No provider account
or live model calls are needed for setup, the demo, or the automated tests.

## Problem

A dependency upgrade can look syntactically correct while changing application
behavior. PatchPilot makes migration work bounded and inspectable: gather relevant
context, propose a narrow patch, verify it in isolation, repair within a fixed budget,
and retain the evidence behind the final outcome.

## Scope

The MVP supports five fixed Python dependency/API migration families: Pydantic,
SQLAlchemy, HTTPX, OpenAI Python SDK, and Celery. It does not implement arbitrary
features, cross-language rewrites, deployment, or automatic merging. `READY_FOR_PR`
means a verified branch is ready for human review; it does not mean a PR was opened
or merged.

## Core Workflow

```text
Request → capability gate → repository analysis → bounded context
→ migration plan → patch → sandbox verification
→ bounded repair/review if needed → human approval
→ target branch → final verification → READY_FOR_PR
```

Unsupported requests stop early. Unresolved migration failures escalate to
`NEEDS_HUMAN_REVIEW`; model/tool/environment failures follow separate error routes.

## Architecture

[Architecture diagram and design notes](docs/architecture.md) distinguish AI
reasoning from deterministic control. The [Orchestrator](src/patchpilot/workflow/runner.py)
uses one [state machine](src/patchpilot/workflow/state.py); selecting a model never
selects a state transition. AI-backed components are the planner, patch generator,
failure analyzer, repair generator, conditional Reviewer, and semantic Capability
Classifier when deterministic scope checks leave ambiguity.

## Key Engineering Decisions

**PatchPilot uses AI where semantic reasoning and code generation are useful, but
treats AI outputs as untrusted proposals until deterministic controls validate them.**

| Layer | Question it answers |
| --- | --- |
| Deterministic guardrails / Orchestrator | Is this action allowed? |
| Independent AI Reviewer, when necessary | Does this ambiguous proposal make sense given the evidence? |
| Deterministic verification | Did the change actually work within the available checks? |

- **Deterministic control and capability checks:** enforce scope and legal transitions;
  use semantic classification only for unresolved intent.
- **Deterministic context ranking and budgets:** keep evidence selection reproducible
  and bounded, with focused expansion when failures expose missing context.
- **Schema-validated proposals, sandbox first:** reject malformed or out-of-scope
  edits before they can modify the target branch. A sandbox is an isolated working
  copy, not a hardened security boundary for hostile code.
- **Conditional Reviewer and three total attempts:** spend extra reasoning on
  ambiguous repairs without allowing an unbounded retry loop.
- **Separate checkpoints:** `repair_base_checkpoint` can retain a failing migration
  candidate; `last_verified_stable` represents code that passed verification.
- **Approval and final verification:** human approval precedes target-branch edits;
  the exact promoted patch is checked again. Approval is distinct from code correctness.
- **Generic family configuration and separate failure classes:** reuse the workflow
  across migrations, and never treat a provider/tool/environment outage as a reason
  to repair application code.

### Repair loop

Attempt 1 is the initial migration, Attempt 2 the first repair, and Attempt 3 the
second repair. **There is no Attempt 4.** The Failure Analyzer uses test output,
the current diff, plan, and selected context. Deterministic policy may approve a
clear repair; an ambiguous repair goes to an independent Change Reviewer. Evidence
can expand within the same context budgets. A degraded repair rolls back to its
`repair_base_checkpoint`; a verified candidate may become `last_verified_stable`.
An unresolved Attempt 3 ends in `NEEDS_HUMAN_REVIEW`.

### Persistence / auditability

SQLite stores run state, transition history, attempts, Reviewer decisions,
verification results, and telemetry. Git and filesystem artifacts retain snapshots,
checkpoints, diffs, branches, and exported records. Together they explain the selected
context, proposals, changes, failures, reviews, rollbacks, and final state. They do
not retain an exact replay of every outbound provider request. See the
[artifact guide](artifacts/README.md) for navigation and historical telemetry caveats.

## Benchmark / Evaluation

**CONTROLLED / TEST-DOUBLE EVALUATION.** All five happy paths reached `READY_FOR_PR`
on Attempt 1. The additional persisted scenarios below exercise repair and escalation;
they are scenario coverage, not estimates of real model success rates.

| Fixed migration | Repair scenario final state | Total attempts | Repair succeeded? | Reviewer? | Context expansion? |
| --- | --- | ---: | --- | --- | --- |
| Pydantic v1 → v2 | READY_FOR_PR | 2 | Yes | No | No |
| SQLAlchemy 1.4 → 2.0 | READY_FOR_PR | 2 | Yes | No | No |
| HTTPX 0.27 → 0.28 | READY_FOR_PR | 3 | Yes | No | No |
| OpenAI Python SDK 0.28 → 1.x | READY_FOR_PR | 2 | Yes | Yes | Yes, once |
| Celery 4 → 5 | NEEDS_HUMAN_REVIEW | 3 | No; intentional max-attempt case | Yes | No |

Source: [persisted benchmark summary](artifacts/benchmark/prompt4_summary.json),
including its per-run records. The Celery happy path passed; its injected-failure
scenario exhausted the repair budget and never reached target verification.

[Final cleanup regression](artifacts/validation/README.md): **137 passed, 0 failed,
0 skipped, 0 pytest warnings**. These tests validate workflow behavior, not live model quality.

## Model Selection & Trade-offs

- **Live provider model benchmarking: NOT MEASURED / DEFERRED**
- **OpenAI API key: NOT REQUIRED**
- **Real Sol/Terra cost and latency claims: NOT MADE**

The [evaluation framework](src/patchpilot/evaluation/) keeps architecture, prompts,
fixtures, and verification criteria fixed. Its intended sequence is an all-Sol
baseline, then Terra in one of the six LLM components at a time. Quality comes first;
cost and latency only matter after quality evidence is adequate. p95 captures tail
behavior that averages can hide. The approximately **20% p95 slowdown guideline
is a portfolio comparison rule, not a production SLA**; a larger slowdown needs
an explicit cost/quality justification.

No live quality differences, token costs, dollar costs, average latencies, or p95
latencies have been measured. All six component decisions are `INCONCLUSIVE`;
there is no evidence-selected final assignment or optimized live rerun. The existing
Sol adapter default is not a measured winner. [Configuration](config/model_evaluation.json)
and [evaluation trade-offs](artifacts/evaluation/model_tradeoffs.md) document the
method, unknown values, sample requirements, and missing component coverage.

## Example Run

The persisted [Pydantic repair run](artifacts/benchmark/runs/pydantic/repair2/runs/329dda9efc2947b7a2f8424e41a105d1/summary.json)
shows this controlled sequence:

```text
Upgrade Pydantic v1 → v2 → repository analysis → selected context → migration plan
→ initial patch → sandbox test failure → evidence-based repair on Attempt 2
→ sandbox verification passes → APPROVE → target branch
→ final verification passes → READY_FOR_PR
```

See [the short walkthrough](docs/example_run.md) for the exact context, plan,
failure, repair, approval, and verified patch. The demo scripts supply `APPROVE`
explicitly and record the actor as `simulated-human`.

## Known Limitations

- Python-only MVP, limited to the five dependency/API migration families above.
- Intentionally small benchmark repositories; passing tests cannot prove behavior
  outside available regression coverage.
- Controlled proposals exercise workflow behavior, not real model competence.
  Live provider benchmarking was not performed.
- Repair/review/classification may have insufficient natural call coverage for
  model substitution; independent quality labels and more observations are needed.
- No arbitrary feature development, cross-language rewrite, automatic production
  deployment, or automatic merge. Human review remains necessary before merge.
- Local Git isolation is not OS/container isolation; verification executes repository
  code with the local process's permissions.

## How to Run

Use a Unix-like environment with Python 3.10+, Git, ripgrep (`rg`), and network access
for dependency installation. Run commands from the repository root:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
scripts/setup_prompt4_envs.sh
scripts/verify_fixture.sh
.venv/bin/python scripts/run_controlled_repair.py
.venv/bin/python -m pytest -ra
```

The setup script creates isolated verification environments in `/tmp`, including
Python 3.10 for the Celery 4 baseline. It installs tools via `uv` and recreates the
family environments, so do not run setup concurrently with tests. The development
environment pins Pydantic v1 for the original fixture; migrated code is verified in
separate target-version environments.

The repair demo writes a fresh `artifacts/controlled-repair-*/` directory. To regenerate
the complete controlled benchmark evidence, run
`.venv/bin/python scripts/run_prompt4_benchmark.py`; this updates the tracked benchmark
summary and creates new per-run artifacts. To inspect the deferred evaluation status,
run `.venv/bin/python -m patchpilot.evaluation.runner`—no provider call is made.

## Prompt Documentation

Start with the [Prompt Outline / Index](docs/prompts/00_prompt_outline.md), which links
all six full prompts and their versions. Also see the
[architecture](docs/architecture.md), [interview talking points](docs/interview_talking_points.md),
[example run](docs/example_run.md), and [artifact guide](artifacts/README.md).
