# PatchPilot

Part 1 provides a canonical Pydantic v1 application, deterministic repository tools,
and isolated Git working copies. Part 2 adds the first happy-path migration workflow
with SQLite run records, bounded context, model telemetry, approval, and target-branch
verification.

## Setup and verification

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
scripts/verify_fixture.sh
.venv/bin/python -m pytest
```

The fixture is immutable benchmark input. A `Sandbox` creates an isolated Git copy.
Prompt 2 creates candidate checkpoints for AI patches and promotes them only after
verification passes. `rollback()` restores the previous verified stable snapshot.
SQLite records workflow metadata. Git and the filesystem hold code artifacts.
Prompt sources live in `docs/prompts/` with stable name and version headers.

## Part 2 workflow

Create a separate Python environment containing Pydantic v2, pytest, mypy, and ruff.
For an optional live Sol run, set `OPENAI_API_KEY`. Then run:

```bash
.venv/bin/python -m patchpilot.workflow \
  --canonical fixtures/pydantic_v1_app \
  --artifacts /path/to/run-artifacts \
  --database /path/to/run.db \
  --verification-python /path/to/pydantic-v2-env/bin/python \
  --approval APPROVE
```

The command creates a target Git repository under the artifacts directory, applies
the verified sandbox patch to a new branch after approval, and stores run records in
SQLite. Use `DECLINE` to stop at the approval gate. Set
`PATCHPILOT_SOL_INPUT_USD_PER_M` and `PATCHPILOT_SOL_OUTPUT_USD_PER_M` to record cost
estimates using configured per-million-token rates.

## Part 3 bounded repair

Prompt 3 extends the same workflow with failure analysis, conditional independent review,
and at most three total verification attempts. Repairs stay in the sandbox until full
verification passes. Add `--repair` to the live command to enable this path.

The acceptance run uses a controlled model with real sandbox and Pydantic v2
verification, so it needs no OpenAI API key:

```bash
.venv/bin/python scripts/run_controlled_repair.py
```

Run evidence is written under `artifacts/controlled-repair-*/runs/<run_id>/`.
Live Sol quality, cost, and latency evaluation is deferred.

## Part 4 fixed migration benchmark

The fixed benchmark adds SQLAlchemy 1.4 → 2.0, HTTPX 0.27 → 0.28,
OpenAI Python SDK 0.28 → 1.x, and Celery 4 → 5 alongside Pydantic v1 → v2.
Each new fixture starts from an exact old dependency pin. The same state machine,
sandbox, approval gate, target-branch application, and bounded repair loop run
all five cases.

Create the isolated old and new dependency environments, then run the
controlled-model benchmark:

```bash
scripts/setup_prompt4_envs.sh
.venv/bin/python scripts/run_prompt4_benchmark.py
.venv/bin/python -m pytest tests/test_prompt4_benchmark.py
```

The summary is written to `artifacts/benchmark/prompt4_summary.json`; each
run retains its state history, verification results, model telemetry, and patch
under `artifacts/benchmark/runs/`. The controlled model is a test double.
Live Sol quality, token usage, cost, and latency evaluation remains deferred.

## Model Selection & Trade-offs

Part 6 preserves the five migration families above and the deterministic workflow.
The evaluation starts with **Sol for all six LLM components**, then restores that
baseline before substituting **Terra into one component at a time**. Provider model
IDs, repetitions, prices, quality tolerance, and decision thresholds live in
[`config/model_evaluation.json`](config/model_evaluation.json).

**Live evaluation: BLOCKED / NOT YET MEASURED.** `OPENAI_API_KEY` was unavailable
and provider pricing is unconfigured. No quality, cost, average latency, or p95
comparison has been measured; no optimized assignment is claimed.

| Component | Terra comparison | Final assignment / rationale |
| --- | --- | --- |
| Migration Planner | INCONCLUSIVE | Pending live evidence |
| Patch Generator | INCONCLUSIVE | Pending live evidence |
| Failure Analyzer | INCONCLUSIVE | Pending live coverage and evidence |
| Repair Generator | INCONCLUSIVE | Pending live coverage and evidence |
| Change Reviewer | INCONCLUSIVE | Pending live coverage and adjudicated review decisions |
| Capability Classifier | INCONCLUSIVE | Pending live coverage; exact benchmark requests may bypass it |

Sol remains the existing operational default, not a measured winner. Selection
requires preserved quality first, at least 10% benchmark cost savings, and normally
p95 within 20% of Sol. Larger slowdowns require an explicit trade-off justification.
Unknown usage/prices and test-double costs stay `null`. p95 uses the nearest-rank
method; the default minimum is 20 calls per compared component, so sparse coverage
remains inconclusive.

Inspect preflight without model calls:

```bash
.venv/bin/python -m patchpilot.evaluation.runner
```

After providing API access and verified versioned prices, run into a **fresh** output
directory to preserve prior evidence:

```bash
.venv/bin/python -m patchpilot.evaluation.runner --live \
  --output artifacts/evaluation/live-001
```

The runner records baseline before substitutions, fingerprints frozen inputs,
records environment package versions, and persists every call and completed case.
Independent quality annotations are required before final selection; missing
coverage or labels never count as success. See
[`artifacts/evaluation/model_tradeoffs.md`](artifacts/evaluation/model_tradeoffs.md)
for metric definitions, adjudication, reproduction, limitations, and artifact links.
The optimized end-to-end run remains pending. Existing scripted-model tests validate
workflow paths separately and cannot establish Sol/Terra superiority.
