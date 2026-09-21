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
