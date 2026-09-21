Prompt: 01_environment_fixture
Version: v1
Purpose: Environment, fixture repository, sandbox, verification, and snapshot foundation

You are implementing **Part 1 of PatchPilot**, an AI-powered code migration and verification system.

This prompt establishes the project foundation only.

Do **not** implement the migration workflow, Orchestrator, LLM calls, Migration Planner, Failure Analyzer, AI Reviewer, repair loop, or model optimization yet.

The goal is to create a stable and repeatable environment that later prompts can safely build on.

# 1. Create the PatchPilot Repository Structure

Create a clean Python project structure similar to:

```text
patchpilot/
├── src/
│   └── patchpilot/
│       ├── __init__.py
│       ├── sandbox/
│       ├── tools/
│       └── storage/
│
├── fixtures/
│   └── pydantic_v1_app/
│       ├── src/
│       ├── tests/
│       ├── pyproject.toml
│       └── README.md
│
├── docs/
│   └── prompts/
│
├── scripts/
├── tests/
├── pyproject.toml
└── README.md
```

Keep the structure simple.

Do not create unnecessary abstractions or placeholder services that are not required by this prompt.

# 2. Prompt Storage and Versioning

Create:

```text
docs/prompts/01_environment_fixture.md
```

Store this implementation prompt there.

Include simple metadata at the top:

```text
Prompt: 01_environment_fixture
Version: v1
Purpose: Environment, fixture repository, sandbox, verification, and snapshot foundation
```

Future PatchPilot runs must eventually be able to reference which prompt/version produced a change.

Do not implement full run tracing yet, but establish the prompt-storage convention now.

# 3. Create the Canonical Pydantic v1 Fixture

Create a small but realistic Python application pinned to **Pydantic v1**.

The canonical fixture dependency must be pinned exactly to `pydantic==1.10.26` in its dependency configuration. Do not use a Pydantic version range. This exact version is the reproducible baseline for later migration and model-comparison runs. Update any related lock/configuration files if required.

This repository will later be migrated by PatchPilot.

It must contain multiple source files so that the future migration is not a trivial one-file search-and-replace.

Use a simple domain such as:

```text
User
Order
Shared/Base model configuration
```

Include representative Pydantic v1-specific behavior such as:

```text
BaseModel
@validator
@root_validator where appropriate
v1-style Config
model parsing
serialization / dict behavior
shared configuration
```

Keep the fixture understandable and intentionally small.

The fixture must be treated as the **canonical benchmark repository**.

It must remain unchanged across future PatchPilot experiments.

# 4. Baseline Regression Tests

Create tests describing the existing application behavior.

Include representative cases for:

* valid model creation
* invalid input rejection
* field validation
* shared/base-model behavior
* serialization
* interactions involving more than one model

These tests will become the regression suite used after migration.

Important:

Do not design weak tests merely to make future migration easier.

The baseline tests should represent behavior that PatchPilot must preserve.

# 5. Deterministic Verification Tooling

Configure the fixture so it can be checked using:

```text
pytest
mypy
ruff
```

Also implement a basic runtime/import sanity check.

For example:

```bash
python -c "import <fixture_package>"
```

Create one helper script, such as:

```text
scripts/verify_fixture.sh
```

or an equivalent Python command.

It must execute the required verification checks and return a non-zero exit code if any required check fails.

The baseline fixture must be fully healthy before this prompt is considered complete.

# 6. Deterministic Repository Tooling Foundation

Prepare basic deterministic tools that later prompts can reuse.

At minimum support:

### File discovery

List source, test, configuration, and dependency files.

### Text/code search

Support repository search using `ripgrep (rg)` when available.

### Python structure inspection

Use Python `ast` where useful to identify:

* imports
* classes
* functions
* decorators
* inheritance relationships

Do not implement AI-based repository analysis.

Do not implement migration-specific reasoning yet.

This prompt only establishes the deterministic primitives.

# 7. Sandbox / Isolated Working Copy

Implement a deterministic sandbox utility.

Given the canonical fixture repository, it must be able to:

1. create an isolated working copy,
2. allow changes only inside that working copy,
3. preserve the canonical fixture unchanged,
4. reset or delete the sandbox safely.

Future PatchPilot migration attempts will run inside these sandboxes.

Do not run migrations yet.

# 8. Git Snapshot Foundation

Use Git as the code snapshot/checkpoint mechanism.

The system must be able to support:

```text
canonical/original state
→ working copy
→ change
→ inspect diff
→ create checkpoint
→ rollback
```

Provide deterministic utilities for:

* identifying changed files
* retrieving the current diff
* reading the original version of a file
* reading the current version
* creating a checkpoint/snapshot
* rolling back to the previous stable checkpoint

Do not implement repair logic.

This prompt only establishes the snapshot primitives required by later prompts.

# 9. Last-Stable-Snapshot Rule

Establish this project invariant:

> A code-changing workflow must always know the last stable repository snapshot before applying another modification.

For Part 1, demonstrate that this mechanism works.

Later repair prompts will depend on it.

# 10. Storage Foundation

PatchPilot will later use:

```text
SQLite → workflow/run metadata
Git/filesystem → code artifacts and snapshots
```

For this prompt, create only the minimal SQLite/storage initialization needed to establish this convention.

Do not yet implement the complete migration run persistence model.

Full run/state persistence will be implemented when the workflow is added in Prompt 2.

# 11. Infrastructure Tests

Add tests for PatchPilot's foundation itself.

At minimum test:

### Sandbox isolation

Modify a sandbox file and prove that the canonical fixture remains unchanged.

### Diff detection

Modify a sandbox file and verify that changed files and diff are correctly detected.

### Snapshot / rollback

Create a checkpoint, modify code, then restore the previous stable state.

### Original/current file retrieval

Verify that the tool can retrieve both the original and current version of a modified file.

### Baseline fixture health

Verify that the clean canonical fixture passes all required baseline verification checks.

### Prompt storage

Verify that:

```text
docs/prompts/01_environment_fixture.md
```

exists and contains the prompt version metadata.

# 12. Important Boundaries

Do NOT implement:

* Orchestrator
* workflow state machine
* MigrationRequest processing
* Capability Gate
* Context Manager
* Migration Planner
* LLM/model calls
* code migration
* Pydantic v2 conversion
* Failure Analyzer
* repair loop
* AI Reviewer
* model routing
* model comparison
* PR creation
* production deployment
* vector database
* LangGraph
* UI

Do not implement future prompts early.

# 13. No Agent State Yet

This prompt intentionally does not introduce the PatchPilot agent/orchestrator state machine.

There should be no workflow states such as:

```text
PLANNING
PATCHING
VERIFYING
REPAIRING
READY_FOR_PR
```

yet.

The explicit state machine begins in Prompt 2.

# Acceptance Criteria

Before finishing, verify all of the following:

```text
[ ] PatchPilot project structure exists

[ ] docs/prompts/01_environment_fixture.md exists

[ ] Prompt version metadata is stored

[ ] Canonical Pydantic v1 fixture exists

[ ] Canonical fixture dependency is exactly pydantic==1.10.26

[ ] Fixture contains multiple realistic Pydantic v1 usages

[ ] Fixture contains multiple source files

[ ] Baseline regression tests pass

[ ] pytest passes

[ ] mypy passes if configured as required

[ ] ruff passes

[ ] runtime/import sanity check passes

[ ] deterministic repository/file search primitives exist

[ ] Python AST inspection primitives exist

[ ] sandbox working copy is isolated from canonical fixture

[ ] canonical fixture remains unchanged after sandbox modifications

[ ] Git diff identifies sandbox changes

[ ] original/current file versions can be retrieved

[ ] checkpoint/snapshot creation works

[ ] rollback restores the previous stable snapshot

[ ] minimal SQLite/storage foundation exists

[ ] infrastructure tests pass

[ ] no migration, orchestration, LLM, or repair logic was implemented
```

# Final Response

At completion, report concisely:

1. files created or changed
2. final repository structure
3. fixture design
4. exact baseline verification commands
5. test results
6. sandbox isolation test result
7. snapshot/rollback test result
8. SQLite/storage foundation created
9. prompt file/version created
10. any limitations or decisions that Prompt 2 needs to know

Do not claim success unless the required commands were actually executed and passed.
