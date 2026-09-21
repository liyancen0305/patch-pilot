"""Prompt 5 deterministic scope, system failure, and routing contracts."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import pytest
from test_happy_path import FIXTURE, V2_PYTHON, ScriptedSol
from test_prompt3_repair import RepairModel

from patchpilot.workflow import RunStore, VerificationRunner, Workflow
from patchpilot.workflow.model import ModelClient
from patchpilot.workflow.schema import (
    MigrationRequest,
    State,
    VerificationCheck,
    VerificationResult,
)

GOAL = "Upgrade Pydantic v1 to Pydantic v2"


class ControlledBackend:
    model = "prompt5-controlled-model"

    def __init__(self, classification: str = "SUPPORTED_MIGRATION",
                 bad_plan: bool = False, bad_patch: str = "",
                 planner_errors: int = 0) -> None:
        self.classification = classification
        self.bad_plan = bad_plan
        self.bad_patch = bad_patch
        self.planner_errors = planner_errors
        self.components: list[str] = []
        self.base = ScriptedSol()

    def complete(self, component: str, payload: dict[str, Any],
                 schema: type[Any]) -> tuple[dict[str, Any], int, int]:
        self.components.append(component)
        if component == "CapabilityClassifier":
            if self.classification == "MALFORMED":
                return {"classification": "nonsense"}, 1, 1
            return {"classification": self.classification,
                    "reason": "classified from explicit scope evidence",
                    "detected_migration_type": "pydantic",
                    "scope_risk": "low",
                    "missing_information": ["intended migration"]
                    if self.classification == "NEED_MORE_INFORMATION" else []}, 1, 1
        if component == "Migration Planner" and self.planner_errors:
            self.planner_errors -= 1
            raise RuntimeError("temporary provider failure")
        result, input_tokens, output_tokens = self.base.complete(component, payload, schema)
        if component == "Migration Planner" and self.bad_plan:
            result = dict(result)
            result["planned_changes"][0]["file"] = "../production/credentials.env"
        if component == "Patch Generator" and self.bad_patch:
            result = dict(result)
            if self.bad_patch == "path":
                result["changes"][0]["path"] = "../../production/credentials.env"
            else:
                for item in result["changes"]:
                    if item["path"] == "tests/test_shop.py":
                        item["content"] = item["content"].replace('assert user.name == "Ada"',
                                                                     'assert user.name == "Other"')
        return result, input_tokens, output_tokens


class FastVerifier(VerificationRunner):
    def run(self, root: Path) -> VerificationResult:
        names = ("Pydantic v2 migration", "installed Pydantic v2", "pytest",
                 "mypy", "ruff", "runtime/import")
        return VerificationResult(passed=True, checks=[
            VerificationCheck(name=name, command=[], exit_code=0, output="passed")
            for name in names])


def request(goal: str, repository: Path = FIXTURE, language: str = "Python") -> MigrationRequest:
    return MigrationRequest(repository=str(repository), migration_goal=goal, language=language)


def execute(tmp_path: Path, goal: str = GOAL,
            backend: Any | None = None, verifier: VerificationRunner | None = None,
            canonical: Path = FIXTURE, repair: bool = False) -> tuple[Any, RunStore, Any]:
    model = backend or ControlledBackend()
    store = RunStore(tmp_path / "runs.db")
    workflow = Workflow(store, ModelClient(model, store, retries=1),
                        verifier or FastVerifier(V2_PYTHON), repair_enabled=repair)
    run = workflow.run(canonical, tmp_path / "artifacts", request=request(goal, canonical))
    assert run.prompt_name == "05_guardrails_failures" and run.prompt_version == "v1"
    assert store.load(run.run_id).current_state == run.current_state
    return run, store, model


def states(store: RunStore, run_id: str) -> list[State]:
    return [event.next_state for event in store.history(run_id)]


@pytest.mark.parametrize("goal,rule", [
    ("Rewrite Python to Java", "same_language_only"),
    ("Add a new payment feature", "migration_only"),
    ("Large architectural redesign", "migration_only"),
    ("Deploy automatically to production", "no_automatic_deployment"),
    ("Drop production database", "no_destructive_production_actions"),
])
def test_deterministic_unsupported_stops_before_model(
        goal: str, rule: str, tmp_path: Path) -> None:
    run, store, model = execute(tmp_path, goal)
    assert run.current_state == State.UNSUPPORTED
    assert run.unsupported_decision and run.unsupported_decision.violated_scope_rule == rule
    assert states(store, run.run_id) == [State.RECEIVED, State.SCOPE_CHECK, State.UNSUPPORTED]
    assert not model.components and not store.model_calls(run.run_id)


@pytest.mark.parametrize("classification,terminal", [
    ("SUPPORTED_MIGRATION", State.READY_FOR_PR),
    ("UNSUPPORTED", State.UNSUPPORTED),
    ("NEED_MORE_INFORMATION", State.NEEDS_HUMAN_REVIEW),
])
def test_ambiguous_classifier_routes_and_persists_telemetry(
        classification: str, terminal: State, tmp_path: Path) -> None:
    run, store, model = execute(tmp_path, "Modernize this legacy authentication module",
                                ControlledBackend(classification))
    path = states(store, run.run_id)
    assert path[:3] == [State.RECEIVED, State.SCOPE_CHECK, State.CAPABILITY_CLASSIFYING]
    assert path[-1] == terminal
    assert model.components[0] == "CapabilityClassifier"
    assert store.model_calls(run.run_id)[0].component == "CapabilityClassifier"
    assert store.model_calls(run.run_id)[0].prompt_version == "v1"
    assert run.capability_classification and run.capability_classification.classification == classification
    if classification == "SUPPORTED_MIGRATION":
        assert path[3:5] == [State.VERIFICATION_CAPABILITY_CHECK, State.ANALYZING_REPO]
        assert run.verification_capability and run.verification_capability.sufficient
    else:
        assert "Migration Planner" not in model.components


def test_malformed_classifier_exhausts_model_retries(tmp_path: Path) -> None:
    run, store, model = execute(tmp_path, "Modernize this legacy authentication module",
                                ControlledBackend("MALFORMED"))
    assert run.current_state == State.FAILED_SYSTEM
    assert states(store, run.run_id)[-4:] == [State.MODEL_ERROR, State.CAPABILITY_CLASSIFYING,
                                            State.MODEL_ERROR, State.FAILED_SYSTEM]
    assert model.components == ["CapabilityClassifier", "CapabilityClassifier"]
    assert len(store.model_calls(run.run_id)) == 2
    assert all(call.error for call in store.model_calls(run.run_id))
    assert len(run.system_failures) == 2


def test_missing_regression_tests_escalates_without_planning(tmp_path: Path) -> None:
    canonical = tmp_path / "unverifiable"
    shutil.copytree(FIXTURE, canonical)
    shutil.rmtree(canonical / "tests")
    run, store, model = execute(tmp_path, backend=ControlledBackend(), canonical=canonical)
    assert run.current_state == State.NEEDS_HUMAN_REVIEW
    assert states(store, run.run_id)[-2:] == [State.VERIFICATION_CAPABILITY_CHECK,
                                             State.NEEDS_HUMAN_REVIEW]
    assert run.verification_capability and not run.verification_capability.sufficient
    assert "cannot safely verify migration" in (run.terminal_reason or "")
    assert not model.components


@pytest.mark.parametrize("bad_plan,bad_patch,rule", [
    (True, "", "repository_scope"),
    (False, "path", "repository_scope"),
    (False, "assertion", "regression_test_protection"),
])
def test_hard_scope_violation_blocks_patch(
        bad_plan: bool, bad_patch: str, rule: str, tmp_path: Path) -> None:
    run, store, _ = execute(tmp_path, backend=ControlledBackend(
        bad_plan=bad_plan, bad_patch=bad_patch))
    path = states(store, run.run_id)
    assert path[-2:] == [State.SCOPE_VIOLATION, State.NEEDS_HUMAN_REVIEW]
    assert run.guardrail_violations[0].rule == rule
    assert run.patch is None and run.sandbox_verification is None
    assert run.target_branch is None
    assert store.load(run.run_id).guardrail_violations


def test_retryable_model_failure_recovers(tmp_path: Path) -> None:
    run, store, model = execute(tmp_path, backend=ControlledBackend(planner_errors=1))
    path = states(store, run.run_id)
    assert run.current_state == State.READY_FOR_PR
    assert path.count(State.MODEL_ERROR) == 1
    assert path[path.index(State.MODEL_ERROR) + 1] == State.PLANNING
    assert [call.error for call in store.model_calls(run.run_id)
            if call.component == "Migration Planner"] == ["temporary provider failure", None]
    assert model.components.count("Migration Planner") == 2
    assert run.retries and run.retries[0].recovered


@pytest.mark.parametrize("recover", [True, False])
def test_tool_failure_recovery_and_exhaustion(
        recover: bool, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from patchpilot.workflow import runner

    original = runner.analyze
    calls = 0

    def flaky(root: Path) -> Any:
        nonlocal calls
        calls += 1
        if not recover or calls == 1:
            raise OSError("temporary repository read failure")
        return original(root)

    monkeypatch.setattr(runner, "analyze", flaky)
    run, store, model = execute(tmp_path)
    path = states(store, run.run_id)
    assert calls == 2
    assert path.count(State.TOOL_ERROR) == (1 if recover else 2)
    assert run.current_state == (State.READY_FOR_PR if recover else State.FAILED_SYSTEM)
    assert (State.ANALYZING_FAILURE in path) is False
    assert bool(model.components) == recover
    assert run.system_failures and run.system_failures[0].category == "TOOL_ERROR"
    assert all(item.recovered == recover for item in run.system_failures)


@pytest.mark.parametrize("recover", [True, False])
def test_environment_failure_recovery_and_exhaustion(
        recover: bool, tmp_path: Path) -> None:
    class FlakyVerifier(FastVerifier):
        calls = 0

        def run(self, root: Path) -> VerificationResult:
            self.calls += 1
            if not recover or self.calls == 1:
                raise OSError("verification Python cannot start")
            return super().run(root)

    run, store, model = execute(tmp_path, verifier=FlakyVerifier(V2_PYTHON))
    path = states(store, run.run_id)
    assert path.count(State.ENVIRONMENT_ERROR) == (1 if recover else 2)
    assert run.current_state == (State.READY_FOR_PR if recover else State.FAILED_SYSTEM)
    assert State.ANALYZING_FAILURE not in path
    assert "Failure Analyzer" not in model.components
    assert run.system_failures and run.system_failures[0].category == "ENVIRONMENT_ERROR"
    assert all(item.recovered == recover for item in run.system_failures)


def test_verifier_cannot_start_does_not_enter_repair(tmp_path: Path) -> None:
    class MissingRunner(FastVerifier):
        def run(self, root: Path) -> VerificationResult:
            return VerificationResult(passed=False, checks=[VerificationCheck(
                name="pytest", command=[], exit_code=127,
                output="No module named pytest")])

    run, store, model = execute(tmp_path, verifier=MissingRunner(V2_PYTHON), repair=True)
    path = states(store, run.run_id)
    assert path[-2:] == [State.ENVIRONMENT_ERROR, State.FAILED_SYSTEM]
    assert State.ANALYZING_FAILURE not in path
    assert "Failure Analyzer" not in model.components
    assert run.failure_classification == "ENVIRONMENT_ERROR"


def test_only_executed_code_failure_enters_repair(tmp_path: Path) -> None:
    class FailOnceVerifier(FastVerifier):
        calls = 0

        def run(self, root: Path) -> VerificationResult:
            self.calls += 1
            if self.calls == 1:
                return VerificationResult(passed=False, checks=[VerificationCheck(
                    name="pytest", command=[], exit_code=1,
                    output="FAILED tests/test_shop.py::test_valid_user_and_normalization "
                           "src/shop/users.py")])
            return super().run(root)

    model = RepairModel()
    run, store, _ = execute(tmp_path, backend=model,
                            verifier=FailOnceVerifier(V2_PYTHON), repair=True)
    path = states(store, run.run_id)
    assert path[path.index(State.VERIFICATION_FAILURE):
                path.index(State.REPAIR_PROPOSED)] == [State.VERIFICATION_FAILURE,
                                                      State.ANALYZING_FAILURE]
    assert run.current_state == State.READY_FOR_PR and run.attempt_number == 2
    assert run.failure_classification == "VERIFICATION_FAILURE"
    assert "Failure Analyzer" in model.components
    assert store.load(run.run_id).repair_attempts


def test_prompt5_persistence_and_contract(tmp_path: Path) -> None:
    run, store, _ = execute(tmp_path)
    assert run.current_state == State.READY_FOR_PR
    assert store.load(run.run_id).verification_capability
    assert (tmp_path / "artifacts/runs" / run.run_id / "run.sqlite3").is_file()
    assert json.loads((tmp_path / "artifacts/runs" / run.run_id /
                       "run.json").read_text())["prompt_name"] == "05_guardrails_failures"
    text = (Path(__file__).parents[1] / "docs/prompts/05_guardrails_failures.md").read_text()
    assert text.startswith("Prompt: 05_guardrails_failures\nVersion: v1\n")


def test_repository_outside_permitted_workspace_is_unsupported(tmp_path: Path) -> None:
    model = ControlledBackend()
    store = RunStore(tmp_path / "runs.db")
    run = Workflow(store, ModelClient(model, store), FastVerifier(V2_PYTHON)).run(
        FIXTURE, tmp_path / "artifacts", request=request(GOAL, tmp_path / "elsewhere"))
    assert run.current_state == State.UNSUPPORTED
    assert run.unsupported_decision and run.unsupported_decision.violated_scope_rule == \
        "permitted_repository_only"
    assert not model.components


def test_missing_verification_python_is_system_environment_failure(tmp_path: Path) -> None:
    run, store, model = execute(tmp_path, verifier=FastVerifier(
        tmp_path / "missing-verification-python"))
    assert states(store, run.run_id)[-3:] == [State.VERIFICATION_CAPABILITY_CHECK,
                                             State.ENVIRONMENT_ERROR, State.FAILED_SYSTEM]
    assert run.system_failures and run.system_failures[0].category == "ENVIRONMENT_ERROR"
    assert all(not item.recovered for item in run.system_failures)
    assert not model.components


def test_sandbox_creation_failure_is_environment_error(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from patchpilot.workflow import runner

    def failed_sandbox(_target: Path) -> Any:
        raise OSError("sandbox filesystem unavailable")

    monkeypatch.setattr(runner, "Sandbox", failed_sandbox)
    run, store, model = execute(tmp_path)
    assert states(store, run.run_id)[-2:] == [State.ENVIRONMENT_ERROR, State.FAILED_SYSTEM]
    assert run.patch is None
    assert "Failure Analyzer" not in model.components


def test_failure_analysis_hard_scope_violation_never_reaches_reviewer(
        tmp_path: Path) -> None:
    class UnsafeRepairModel(RepairModel):
        def complete(self, component: str, payload: dict[str, Any],
                     schema: type[Any]) -> tuple[dict[str, Any], int, int]:
            result = super().complete(component, payload, schema)
            if component == "Failure Analyzer":
                output, input_tokens, output_tokens = result
                output["files_to_modify"] = ["../production/credentials.env"]
                output["reason_for_each_file"][0]["file"] = "../production/credentials.env"
                return output, input_tokens, output_tokens
            return result

    class FailOnceVerifier(FastVerifier):
        calls = 0

        def run(self, root: Path) -> VerificationResult:
            self.calls += 1
            if self.calls == 1:
                return VerificationResult(passed=False, checks=[VerificationCheck(
                    name="pytest", command=[], exit_code=1,
                    output="FAILED tests/test_shop.py::test_valid_user_and_normalization")])
            return super().run(root)

    run, store, model = execute(tmp_path, backend=UnsafeRepairModel(),
                                verifier=FailOnceVerifier(V2_PYTHON), repair=True)
    path = states(store, run.run_id)
    assert path[-2:] == [State.SCOPE_VIOLATION, State.NEEDS_HUMAN_REVIEW]
    assert State.AWAITING_REVIEW not in path
    assert "Change Reviewer" not in model.components
    assert "Repair Generator" not in model.components
    assert run.guardrail_violations[0].rule == "repository_scope"


def test_target_patch_tool_failure_never_claims_success(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from patchpilot.workflow import runner

    original = runner.git

    def failed_apply(root: Path, *args: str) -> str:
        if args and args[0] == "apply":
            raise RuntimeError("git apply failed")
        return original(root, *args)

    monkeypatch.setattr(runner, "git", failed_apply)
    run, store, _ = execute(tmp_path)
    path = states(store, run.run_id)
    assert path[-2:] == [State.TOOL_ERROR, State.FAILED_SYSTEM]
    assert run.target_branch is None and run.final_status == "FAILED_SYSTEM"
    assert run.sandbox_verification and run.sandbox_verification.passed
    assert run.system_failures[-1].component == "Target Patch Tool"


def test_sqlite_persistence_failure_is_tool_error(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import sqlite3

    store = RunStore(tmp_path / "runs.db")
    original = store.save
    writes = 0

    def failing_save(run: Any) -> None:
        nonlocal writes
        writes += 1
        if writes == 5:
            raise sqlite3.OperationalError("database write failed")
        original(run)

    monkeypatch.setattr(store, "save", failing_save)
    model = ControlledBackend()
    run = Workflow(store, ModelClient(model, store), FastVerifier(V2_PYTHON)).run(
        FIXTURE, tmp_path / "artifacts", request=request(GOAL))
    assert run.current_state == State.READY_FOR_PR
    path = states(store, run.run_id)
    assert State.TOOL_ERROR in path
    event = next(item for item in store.history(run.run_id)
                 if item.next_state == State.TOOL_ERROR)
    assert path[path.index(State.TOOL_ERROR) + 1].value == event.previous_state
    assert run.system_failures[0].error_type == "OperationalError"
    assert run.system_failures[0].operation == "save"
    assert run.system_failures[0].error_message == "database write failed"
    assert run.system_failures[0].recovered
    assert "Failure Analyzer" not in model.components


def test_error_recovery_rejects_unrelated_state() -> None:
    from patchpilot.workflow.state import transition

    with pytest.raises(ValueError, match="recorded previous state"):
        transition(State.MODEL_ERROR, State.RECEIVED, "retry", "test")
    assert transition(State.MODEL_ERROR, State.PLANNING, "retry", "test",
                      recovery_state=State.PLANNING).next_state == State.PLANNING
