# PatchPilot

Part 1 provides a canonical Pydantic v1 application, deterministic repository tools,
isolated Git working copies, and a minimal SQLite initializer. It contains no
migration workflow.

## Setup and verification

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
scripts/verify_fixture.sh
.venv/bin/python -m pytest
```

The fixture is immutable benchmark input. Create a `Sandbox` to make an isolated
Git working copy; all edits and checkpoints belong in that copy. A checkpoint
records the current state as the last stable snapshot. A code-changing caller
must read `last_stable_snapshot` before its next edit. `rollback()` restores it.

SQLite is reserved for future run metadata; Git and the filesystem hold code.
Prompt sources live in `docs/prompts/` with a stable name and version header.
