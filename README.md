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
