Prompt: 01_environment_fixture
Version: v1
Purpose: Environment, fixture repository, sandbox, verification, and snapshot foundation

# Part 1: PatchPilot foundation

Implement Part 1 of PatchPilot, an AI-powered code migration and verification
system. This prompt establishes the project foundation only. Do not implement
the migration workflow, Orchestrator, LLM calls, Migration Planner, Failure
Analyzer, AI Reviewer, repair loop, or model optimization yet. The goal is a
stable and repeatable environment that later prompts can safely build on.

## Repository structure

Create a clean Python project with `src/patchpilot/` containing `sandbox/`,
`tools/`, and `storage/`; `fixtures/pydantic_v1_app/` with source, tests,
`pyproject.toml`, and README; `docs/prompts/`; `scripts/`; root tests,
`pyproject.toml`, and README. Keep it simple and avoid placeholder services.

## Prompt storage

Store this prompt at `docs/prompts/01_environment_fixture.md` with the metadata
above. Future runs must eventually reference the producing prompt and version.
Do not implement full run tracing yet.

## Canonical fixture and tests

Create a small realistic application pinned to Pydantic v1, with multiple source
files and User, Order, and shared/base configuration. Include `BaseModel`,
`@validator`, `@root_validator` where appropriate, v1 `Config`, parsing,
serialization and `.dict()` behavior. Treat it as the unchanged canonical
benchmark. Baseline tests must cover valid creation, invalid input, field
validation, shared behavior, serialization, and interactions between models.
Tests should describe real behavior rather than ease a future migration.

## Verification

Configure fixture checks with pytest, mypy, ruff, and runtime import sanity.
Provide one helper command that runs all checks and fails if any fail. The
baseline fixture must pass all checks.

## Deterministic tools

Provide file discovery for source, test, configuration, and dependency files;
repository text search using `rg` when available; and Python `ast` inspection
of imports, classes, functions, decorators, and inheritance. No AI analysis or
migration reasoning.

## Sandbox and snapshots

Create an isolated working copy of the canonical fixture; edits, reset, and
deletion must be confined to that copy. Preserve the canonical fixture. Use
Git for canonical/original state, working changes, diff inspection, checkpoint,
and rollback. Support changed files, current diff, original and current file
contents, checkpoint creation, and restoration of the last stable checkpoint.

Invariant: **A code-changing workflow must always know the last stable
repository snapshot before applying another modification.** Demonstrate this
mechanism in Part 1. Do not run migrations or implement repair logic.

## Storage

Use SQLite for future workflow/run metadata and Git/filesystem for code
artifacts. Initialize only minimal SQLite storage. Full run/state persistence
belongs to Prompt 2.

## Infrastructure tests

Test sandbox isolation and canonical immutability, diff detection, checkpoint
and rollback, original/current retrieval, baseline fixture health, and prompt
file/version metadata.

## Boundaries

Do not implement Orchestrator, workflow state machine, MigrationRequest,
Capability Gate, Context Manager, Migration Planner, LLM/model calls, code
migration, Pydantic v2 conversion, Failure Analyzer, repair loop, AI Reviewer,
model routing/comparison, PR creation, production deployment, vector database,
LangGraph, or UI. Do not introduce states such as PLANNING, PATCHING,
VERIFYING, REPAIRING, or READY_FOR_PR. The state machine begins in Prompt 2.

## Acceptance

Verify the project structure, this versioned prompt, multi-file Pydantic v1
fixture, meaningful tests, pytest/mypy/ruff/import checks, deterministic search
and AST tools, isolated sandbox, immutable canonical source, Git diff and file
retrieval, checkpoint and rollback, minimal SQLite initialization, and passing
infrastructure tests. Report files and structure, fixture design, exact commands,
results, sandbox/snapshot evidence, storage/prompt convention, and limitations
for Prompt 2. Do not claim success unless commands actually passed.
