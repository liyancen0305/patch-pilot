"""Real-verifier controlled benchmark across the five fixed migration families."""

import os
import subprocess
from pathlib import Path

import pytest

from patchpilot.workflow.benchmarks import FAMILIES, MigrationFamily, declared_pin
from patchpilot.workflow.schema import State
from patchpilot.workflow.state import HAPPY_PATH
from patchpilot.workflow.store import RunStore
from scripts.run_prompt4_benchmark import FIXTURES, TARGET_ENV, run_case

OLD_ENV = {
    "sqlalchemy": Path("/tmp/patchpilot-p4-sqlalchemy-old/bin/python"),
    "httpx": Path("/tmp/patchpilot-p4-httpx-old/bin/python"),
    "openai": Path("/tmp/patchpilot-p4-openai-old/bin/python"),
    "celery": Path("/tmp/patchpilot-p4-celery-old/bin/python"),
}


def test_benchmark_set_is_fixed() -> None:
    assert [(family.use_case, family.name) for family in FAMILIES] == [
        (1, "pydantic"), (2, "sqlalchemy"), (3, "httpx"),
        (4, "openai"), (5, "celery")]
    source = (Path(__file__).parents[1] / "src/patchpilot/workflow/runner.py").read_text()
    assert all(name not in source for name in ("sqlalchemy", "httpx", "openai", "celery"))


@pytest.mark.parametrize("family", FAMILIES[1:], ids=lambda family: family.name)
def test_old_fixture_baseline_is_healthy(family: MigrationFamily) -> None:
    name = family.name
    fixture = FIXTURES[name]
    python = OLD_ENV[name]
    assert python.is_file(), f"required old-version environment missing: {python}"
    assert declared_pin(fixture, family) == family.source_pin
    environment = {**os.environ, "PYTHONPATH": "src", "PYTHONDONTWRITEBYTECODE": "1"}
    for command in (["-m", "pytest", "-q", "-p", "no:cacheprovider"],
                    ["-m", "mypy", "src", "tests"],
                    ["-m", "ruff", "check", "src", "tests"],
                    ["-c", f"import {family.runtime_import}"]):
        result = subprocess.run([str(python), *command], cwd=fixture, env=environment,
                                capture_output=True, text=True, check=False)
        assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize("family", FAMILIES, ids=lambda family: family.name)
def test_happy_path_reuses_central_workflow(family: MigrationFamily, tmp_path: Path) -> None:
    assert TARGET_ENV[family.name].is_file()
    run = run_case(family, "happy", tmp_path)
    store = RunStore(tmp_path / family.name / "happy/runs.db")
    history = store.history(run.run_id)
    assert [event.next_state for event in history] == list(HAPPY_PATH)
    assert run.current_state == State.READY_FOR_PR
    assert run.prompt_name == "04_remaining_use_cases" and run.prompt_version == "v1.1"
    assert run.model_type == "test_double"
    assert run.attempt_number == 1
    assert run.context and run.context.items
    assert len(run.context.items) <= run.context.max_snippets
    assert len({item.path for item in run.context.items}) <= run.context.max_files
    assert run.context.total_token_estimate <= run.context.max_context_tokens
    assert all(item.reason for item in run.context.items)
    assert run.patch and run.patch.changed_files
    assert store.load(run.run_id).migration_family == family.name
    assert len(store.model_calls(run.run_id)) == 2


@pytest.mark.parametrize(
    "name,scenario,expected,attempts,reviewer,expansion",
    [
        ("pydantic", "repair2", State.READY_FOR_PR, 2, False, False),
        ("sqlalchemy", "repair2", State.READY_FOR_PR, 2, False, False),
        ("httpx", "repair3", State.READY_FOR_PR, 3, False, False),
        ("openai", "reviewer_context", State.READY_FOR_PR, 2, True, True),
        ("celery", "max3", State.NEEDS_HUMAN_REVIEW, 3, True, False),
    ],
)
def test_existing_repair_paths_generalize(
        name: str, scenario: str, expected: State, attempts: int,
        reviewer: bool, expansion: bool, tmp_path: Path) -> None:
    family = next(item for item in FAMILIES if item.name == name)
    run = run_case(family, scenario, tmp_path)
    store = RunStore(tmp_path / name / scenario / "runs.db")
    states = [event.next_state for event in store.history(run.run_id)]
    assert run.current_state == expected and run.attempt_number == attempts
    assert states.count(State.ANALYZING_FAILURE) == attempts - 1
    assert states.count(State.REPAIRING) == attempts - 1
    assert State.REPAIR_PROPOSED in states
    assert (State.AWAITING_REVIEW in states) == reviewer
    assert bool(run.review_history) == reviewer
    assert (State.GATHERING_ADDITIONAL_CONTEXT in states) == expansion
    assert bool(run.context_expansions) == expansion
    assert len(run.repair_attempts) == attempts - 1
    assert all(item.stable_snapshot_id != item.candidate_checkpoint_id
               for item in run.repair_attempts)
    if expected == State.NEEDS_HUMAN_REVIEW:
        assert states[-1] == State.NEEDS_HUMAN_REVIEW
        assert run.target_branch is None
        assert max(event.attempt_number for event in store.history(run.run_id)) == 3
    else:
        assert State.VERIFIED_PATCH_READY in states
        assert states[-1] == State.READY_FOR_PR
        assert run.target_verification and run.target_verification.passed
    if expansion:
        assert run.context
        assert all(item.new_context.total_token_estimate <= item.new_context.max_context_tokens
                   and len(item.new_context.items) <= item.new_context.max_snippets
                   and len({snippet.path for snippet in item.new_context.items}) <=
                   item.new_context.max_files
                   for item in run.context_expansions)
    persisted = store.load(run.run_id)
    assert persisted.current_state == expected
    assert persisted.migration_family == name
    assert store.model_calls(run.run_id)


def test_prompt4_contract_is_self_contained() -> None:
    contract = (Path(__file__).parents[1] /
                "docs/prompts/04_remaining_use_cases.md").read_text()
    assert contract.startswith("Prompt: 04_remaining_use_cases\nVersion: v1.1\n")
    for requirement in ("SQLAlchemy 1.4", "HTTPX 0.27", "OpenAI Python SDK 0.28",
                        "Celery 4", "Pydantic v1", "max_files", "max_snippets",
                        "max_context_tokens", "NEEDS_HUMAN_REVIEW", "Prompt 6"):
        assert requirement in contract


def test_generic_family_configuration_drives_analyzer_and_verifier() -> None:
    from patchpilot.workflow.repository import analyze
    from patchpilot.workflow.runner import VerificationRunner

    for family in FAMILIES:
        analysis = analyze(FIXTURES[family.name])
        assert analysis.dependency_name == family.dependency_name
        assert analysis.source_version == family.source_version
        assert analysis.target_version == family.target_version
        assert analysis.migration_family == family.name
        assert analysis.migration_api_pattern == family.api_usage_pattern
        assert analysis.migration_api_usages
        assert analysis.evidence
        assert any("rg:" in item for items in analysis.evidence.values() for item in items)
    fields = set(analysis.__fields__)
    assert "pydantic_version" not in fields and "v1_usages" not in fields
    source = (Path(__file__).parents[1] / "src/patchpilot/workflow/repository.py").read_text()
    verifier_source = (Path(__file__).parents[1] / "src/patchpilot/workflow/runner.py").read_text()
    assert all(symbol not in source for symbol in ("root_validator", "ShopModel", "use_case == 1"))
    assert all(symbol not in verifier_source for symbol in
               ("installed Pydantic v2", "import shop", "pydantic-v2-"))
    assert VerificationRunner(TARGET_ENV["httpx"]).python == TARGET_ENV["httpx"]


@pytest.mark.parametrize("family", FAMILIES[:3], ids=lambda family: family.name)
def test_wrong_target_dependency_is_environment_error(
        family: MigrationFamily, tmp_path: Path) -> None:
    from patchpilot.workflow import VerificationRunner, Workflow
    from patchpilot.workflow.model import ModelClient
    from patchpilot.workflow.schema import VerificationCheck, VerificationResult
    from scripts.run_prompt4_benchmark import ControlledBenchmarkModel

    if family.name == "pydantic":
        from test_happy_path import ScriptedSol
        backend = ScriptedSol()
    else:
        backend = ControlledBenchmarkModel(family)

    class MissingTargetVerifier(VerificationRunner):
        def run(self, root: Path) -> VerificationResult:
            return VerificationResult(passed=False, checks=[VerificationCheck(
                name=family.dependency_check_name, command=[], exit_code=1,
                output="target dependency unavailable")])

    store = RunStore(tmp_path / "runs.db")
    run = Workflow(store, ModelClient(backend, store),
                   MissingTargetVerifier(TARGET_ENV[family.name]),
                   repair_enabled=True, benchmark_mode=True).run(
                       FIXTURES[family.name], tmp_path / "artifacts")
    assert run.current_state == State.ENVIRONMENT_ERROR
    assert run.attempt_number == 1
    assert not run.failure_analyses and not run.repair_attempts
    assert store.history(run.run_id)[-1].next_state == State.ENVIRONMENT_ERROR
    assert store.load(run.run_id).prompt_version == "v1.1"


@pytest.mark.parametrize("family", FAMILIES, ids=lambda family: family.name)
def test_branch_and_commit_labels_come_from_family_metadata(
        family: MigrationFamily, tmp_path: Path) -> None:
    # The existing integration path exercises the same branch/commit code for all families.
    run = run_case(family, "happy", tmp_path)
    target = Path(run.repository_identifiers["target"])
    assert run.target_branch == f"patchpilot/{family.branch_slug}-{run.run_id[:8]}"
    message = subprocess.check_output(["git", "log", "-1", "--format=%s"],
                                      cwd=target, text=True).strip()
    assert message == f"Apply verified {family.commit_label} migration patch"


@pytest.mark.parametrize("name,python", [
    ("pydantic", Path(__file__).parents[1] / ".venv/bin/python"),
    ("sqlalchemy", OLD_ENV["sqlalchemy"]),
    ("httpx", OLD_ENV["httpx"]),
])
def test_real_wrong_dependency_environment_stops_at_capability_gate(
        name: str, python: Path, tmp_path: Path) -> None:
    from patchpilot.workflow import VerificationRunner, Workflow
    from patchpilot.workflow.model import ModelClient
    from scripts.run_prompt4_benchmark import ControlledBenchmarkModel

    family = next(item for item in FAMILIES if item.name == name)
    store = RunStore(tmp_path / "runs.db")
    run = Workflow(store, ModelClient(ControlledBenchmarkModel(family), store),
                   VerificationRunner(python), repair_enabled=True,
                   benchmark_mode=True).run(FIXTURES[name], tmp_path / "artifacts")
    assert run.current_state == State.ENVIRONMENT_ERROR
    assert run.attempt_number == 1
    assert not store.model_calls(run.run_id)
    assert [event.next_state for event in store.history(run.run_id)] == [
        State.RECEIVED, State.SCOPE_CHECK, State.ENVIRONMENT_ERROR]
