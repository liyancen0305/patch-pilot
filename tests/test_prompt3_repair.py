"""Prompt 3 bounded repair through the real sandbox and verifier."""

import hashlib
import json
import os
import sqlite3
import subprocess
from pathlib import Path
from typing import Any, cast

import pytest
from test_happy_path import ScriptedSol

from patchpilot.sandbox import Sandbox
from patchpilot.workflow import RunStore, VerificationRunner, Workflow
from patchpilot.workflow.model import ModelClient
from patchpilot.workflow.repair import (
    degraded,
    direct_approval_reason,
    validate_analysis,
)
from patchpilot.workflow.repository import analyze, expand_context, select_context
from patchpilot.workflow.runner import apply_proposal
from patchpilot.workflow.schema import (
    ContextBundle,
    FailureAnalysis,
    FileChange,
    MigrationPlan,
    PatchProposal,
    PlannedChange,
    RepairFileReason,
    RunRecord,
    State,
    VerificationCheck,
    VerificationResult,
)
from patchpilot.workflow.state import transition

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures/pydantic_v1_app"
V2_PYTHON = Path(os.environ.get("PATCHPILOT_V2_PYTHON", "/tmp/patchpilot-pydantic2-venv/bin/python"))


class RepairModel:
    model = "controlled-repair-test-double"

    def __init__(self, *, repair_pass_on: int = 1, ambiguous: bool = False,
                 more_evidence: bool = False, reject: bool = False,
                 degraded_first: bool = False, degraded_on: int | None = None) -> None:
        self.base = ScriptedSol()
        self.repair_pass_on = repair_pass_on
        self.ambiguous = ambiguous
        self.more_evidence = more_evidence
        self.reject = reject
        self.degraded_first = degraded_first
        self.degraded_on = degraded_on
        self.reviews = 0
        self.repairs = 0
        self.components: list[str] = []

    def complete(self, component: str, payload: dict[str, Any],
                 schema: type[Any]) -> tuple[dict[str, Any], int, int]:
        self.components.append(component)
        if component == "Migration Planner":
            return self.base.complete(component, payload, schema)
        if component == "Patch Generator":
            raw_proposal, _, _ = self.base.complete(component, payload, schema)
            proposal = cast(dict[str, Any], raw_proposal)
            for change in proposal["changes"]:
                if change["path"] == "src/shop/users.py":
                    change["content"] = change["content"].replace(
                        "value = value.lower()", "value = value.strip()")
            return proposal, 0, 0
        if component == "Failure Analyzer":
            assert payload["current_diff"] and payload["verification_result"]
            assert payload["original_relevant_code"] and payload["current_relevant_code"]
            return {
                "failure_type": "migration_behavior_regression",
                "likely_root_cause": "email normalizer no longer lowercases",
                "supporting_evidence": ["test_valid_user_and_normalization fails"],
                "proposed_repair": "restore lowercase normalization",
                "files_to_modify": ["src/shop/users.py"],
                "reason_for_each_file": [{"file": "src/shop/users.py",
                    "reason": "email normalization regression",
                    "supporting_evidence": "failing email assertion",
                    "expected_effect": "preserve lowercase email",
                    "required_verification": "full suite"}],
                "additional_context_needed": [],
                "confidence": 0.5 if self.ambiguous else 0.95,
            }, 0, 0
        if component == "Change Reviewer":
            self.reviews += 1
            decision = ("REJECT" if self.reject else
                        "NEED_MORE_EVIDENCE" if self.more_evidence and self.reviews == 1 else
                        "APPROVE")
            return {"decision": decision, "reason": "independent review",
                    "supporting_evidence": ["failing regression test"],
                    "risk": "low", "additional_context_needed": ["tests/test_shop.py"]
                    if decision == "NEED_MORE_EVIDENCE" else [],
                    "required_verification": ["full suite"]}, 0, 0
        if component == "Repair Generator":
            self.repairs += 1
            current = payload["current_relevant_code"]["src/shop/users.py"]
            if (self.degraded_first and self.repairs == 1) or self.degraded_on == self.repairs:
                replacement = current.replace("name: str", "name: UndefinedType")
            elif self.repairs >= self.repair_pass_on:
                replacement = current.replace("value = value.strip()", "value = value.lower()")
            else:
                replacement = current.replace("value = value.strip()",
                                              "value = value.strip().strip()")
            return {"changes": [{"path": "src/shop/users.py", "content": replacement}],
                    "rationale": "repair email normalization"}, 0, 0
        raise AssertionError(component)


def _run(tmp_path: Path, model: RepairModel) -> tuple[RunRecord, RunStore]:
    assert V2_PYTHON.is_file(), f"required Pydantic v2 verifier missing: {V2_PYTHON}"
    store = RunStore(tmp_path / "runs.db")

    class TrackingVerifier(VerificationRunner):
        def run(self, root: Path) -> VerificationResult:
            target = tmp_path / "artifacts/target"
            if root != target:
                status = subprocess.check_output(["git", "-C", str(target), "status",
                                                  "--porcelain"], text=True).strip()
                branch = subprocess.check_output(["git", "-C", str(target), "branch",
                                                  "--show-current"], text=True).strip()
                assert not status and branch == "main"
            return super().run(root)

    run = Workflow(store, ModelClient(model, store), TrackingVerifier(V2_PYTHON),
                   repair_enabled=True).run(FIXTURE, tmp_path / "artifacts", approval="APPROVE")
    return run, store


def _states(store: RunStore, run_id: str) -> list[State]:
    return [event.next_state for event in store.history(run_id)]


def test_attempt_one_fails_direct_repair_attempt_two_passes(tmp_path: Path) -> None:
    before = {path.relative_to(FIXTURE): hashlib.sha256(path.read_bytes()).hexdigest()
              for path in FIXTURE.rglob("*") if path.is_file()}
    model = RepairModel()
    run, store = _run(tmp_path, model)
    states = _states(store, run.run_id)
    assert run.current_state == State.READY_FOR_PR and run.attempt_number == 2
    assert run.prompt_name == "03_failure_repair_path" and run.prompt_version == "v1"
    assert states[7:13] == [State.VERIFYING_SANDBOX, State.ANALYZING_FAILURE,
                           State.REPAIR_PROPOSED, State.REPAIR_APPROVED, State.REPAIRING,
                           State.VERIFYING_SANDBOX]
    assert State.VERIFIED_PATCH_READY in states and states[-1] == State.READY_FOR_PR
    assert len(run.repair_attempts) == 1
    repair = run.repair_attempts[0]
    assert repair.repair_decision_path == "deterministic"
    assert repair.stable_snapshot_id != repair.candidate_checkpoint_id
    assert repair.verification_before and not repair.verification_before.passed
    assert repair.verification_after and repair.verification_after.passed
    assert run.sandbox_verification and run.sandbox_verification.passed
    assert run.target_verification and run.target_verification.passed
    assert run.approval and run.approval.decision == "APPROVE"
    assert model.components == ["Migration Planner", "Patch Generator", "Failure Analyzer",
                                "Repair Generator"]
    target = tmp_path / "artifacts/target"
    assert subprocess.check_output(["git", "-C", str(target), "rev-parse", "main"],
                                   text=True).strip() == run.repository_identifiers["target_main_commit"]
    evidence = tmp_path / "artifacts/runs" / run.run_id
    assert run.patch and (evidence / "verified.patch").read_text() == run.patch.diff
    assert (evidence / "target_branch.diff").read_text() == run.patch.diff
    assert json.loads((evidence / "summary.json").read_text())["attempt_count"] == 2
    assert json.loads((evidence / "repair_attempts.json").read_text())[0]["verification_after"]["passed"]
    assert all(hashlib.sha256((FIXTURE / path).read_bytes()).hexdigest() == digest
               for path, digest in before.items())
    calls = store.model_calls(run.run_id)
    assert all(call.prompt_name == "03_failure_repair_path" and call.prompt_version == "v1"
               for call in calls)
    assert [call.attempt_number for call in calls] == [1, 1, 1, 2]


def test_ambiguous_repair_uses_independent_reviewer(tmp_path: Path) -> None:
    model = RepairModel(ambiguous=True)
    run, store = _run(tmp_path, model)
    assert run.current_state == State.READY_FOR_PR
    states = _states(store, run.run_id)
    assert states.index(State.AWAITING_REVIEW) < states.index(State.REPAIR_APPROVED)
    assert run.review_history[0].decision == "APPROVE"
    assert run.repair_attempts[0].repair_decision_path == "reviewer"
    assert "Failure Analyzer" in model.components and "Change Reviewer" in model.components


def test_reviewer_needs_more_evidence_and_reranks_context(tmp_path: Path) -> None:
    model = RepairModel(ambiguous=True, more_evidence=True)
    run, store = _run(tmp_path, model)
    assert run.current_state == State.READY_FOR_PR
    assert [item.decision for item in run.review_history] == ["NEED_MORE_EVIDENCE", "APPROVE"]
    states = _states(store, run.run_id)
    assert states.index(State.AWAITING_REVIEW) < states.index(State.GATHERING_ADDITIONAL_CONTEXT)
    assert states.count(State.AWAITING_REVIEW) == 2
    assert run.context_expansions and run.context_expansions[0].expansion_reason.startswith("Reviewer")
    assert store.load(run.run_id).context_expansions


def test_reviewer_rejection_never_applies_repair(tmp_path: Path) -> None:
    model = RepairModel(ambiguous=True, reject=True)
    run, store = _run(tmp_path, model)
    assert run.current_state == State.NEEDS_HUMAN_REVIEW
    assert model.repairs == 0 and not run.repair_attempts
    assert _states(store, run.run_id).count(State.REPAIR_REJECTED) == 2
    assert run.review_history[-1].decision == "REJECT"


@pytest.mark.parametrize("pass_on,expected", [(2, State.READY_FOR_PR), (3, State.NEEDS_HUMAN_REVIEW)])
def test_three_attempt_limit(tmp_path: Path, pass_on: int, expected: State) -> None:
    model = RepairModel(repair_pass_on=pass_on)
    run, store = _run(tmp_path, model)
    assert run.current_state == expected and run.attempt_number == 3
    assert len(run.repair_attempts) == 2 and model.repairs == 2
    assert run.repair_attempts[0].stable_snapshot_id == run.repair_attempts[1].stable_snapshot_id
    assert run.repair_attempts[1].repair_base_checkpoint_id == (
        run.repair_attempts[0].candidate_checkpoint_id)
    assert run.repair_attempts[0].repair_base_checkpoint_id != (
        run.repair_attempts[1].repair_base_checkpoint_id)
    assert run.repair_attempts[0].candidate_checkpoint_id != run.repair_attempts[0].stable_snapshot_id
    assert max(event.attempt_number for event in store.history(run.run_id)) == 3
    assert _states(store, run.run_id).count(State.ANALYZING_FAILURE) == 2
    if expected == State.NEEDS_HUMAN_REVIEW:
        assert _states(store, run.run_id)[-1] == State.NEEDS_HUMAN_REVIEW
    with pytest.raises(ValueError, match="attempt number"):
        transition(State.REPAIR_APPROVED, State.REPAIRING, "invalid", "test", 4)


def test_degraded_candidate_rolls_back_stable_snapshot() -> None:
    before = VerificationResult(passed=False, checks=[
        VerificationCheck(name="pytest", command=[], exit_code=1, output="old failure"),
        VerificationCheck(name="mypy", command=[], exit_code=0, output="")])
    after = VerificationResult(passed=False, checks=[
        VerificationCheck(name="pytest", command=[], exit_code=1, output="old failure"),
        VerificationCheck(name="mypy", command=[], exit_code=1, output="new failure")])
    assert degraded(before, after)
    with Sandbox(FIXTURE) as sandbox:
        stable = sandbox.last_stable_snapshot
        original = sandbox.current_file("src/shop/users.py")
        patch = apply_proposal(sandbox, PatchProposal(changes=[FileChange(
            path="src/shop/users.py", content=original + "\n# broken repair\n")],
            rationale="candidate"))
        assert sandbox.last_stable_snapshot == stable != patch.post_snapshot
        sandbox.rollback()
        assert sandbox.last_stable_snapshot == stable
        assert sandbox.current_file("src/shop/users.py") == original


def test_scope_expansion_and_context_budgets() -> None:
    plan = MigrationPlan(summary="test", planned_changes=[PlannedChange(
        file="src/shop/users.py", symbol="User", reason="migration", change="v2",
        expected_effect="same behavior")], affected_files=["src/shop/users.py"],
        risks=[], validation_plan=["pytest"])
    reason = RepairFileReason(file="tests/test_shop.py", reason="migration API",
                              supporting_evidence="failing test path", expected_effect="compatibility",
                              required_verification="pytest")
    analysis = FailureAnalysis(failure_type="migration", likely_root_cause="test API",
        supporting_evidence=["test path"], proposed_repair="update syntax",
        files_to_modify=["tests/test_shop.py"], reason_for_each_file=[reason],
        additional_context_needed=[], confidence=0.95)
    verification = VerificationResult(passed=False, checks=[VerificationCheck(
        name="pytest", command=[], exit_code=1, output="tests/test_shop.py failed")])
    assert direct_approval_reason(FIXTURE, analysis, plan, verification)
    unrelated = analysis.copy(update={"files_to_modify": ["src/shop/base.py"],
        "reason_for_each_file": [reason.copy(update={"file": "src/shop/base.py"})]})
    assert direct_approval_reason(FIXTURE, unrelated, plan, verification) is None
    with pytest.raises(ValueError, match="justification"):
        validate_analysis(analysis.copy(update={"reason_for_each_file": []}))
    repository = analyze(FIXTURE)
    previous: ContextBundle = select_context(FIXTURE, repository, max_files=2,
        max_snippets=3, max_context_tokens=300)
    expanded = expand_context(FIXTURE, repository, previous,
                              "tests/test_shop.py failed", ["src/shop/users.py"],
                              ["tests/test_shop.py"])
    assert len(expanded.items) <= 3
    assert len({item.path for item in expanded.items}) <= 2
    assert expanded.total_token_estimate <= 300
    assert all(item.reason and item.score for item in expanded.items)


def test_degraded_attempt_three_rolls_back_and_stops(tmp_path: Path) -> None:
    model = RepairModel(repair_pass_on=4, degraded_on=2)
    run, store = _run(tmp_path, model)
    assert run.current_state == State.NEEDS_HUMAN_REVIEW
    assert run.attempt_number == 3 and model.repairs == 2
    last = run.repair_attempts[-1]
    assert last.degraded and last.degraded_reason
    assert last.stable_snapshot_id is not None
    assert last.repair_base_checkpoint_id is not None
    assert last.rollback_result == "restored " + last.repair_base_checkpoint_id
    assert last.rollback_target == last.repair_base_checkpoint_id
    assert last.rollback_reason == last.degraded_reason
    assert last.repair_base_checkpoint_id == run.repair_attempts[0].candidate_checkpoint_id
    assert last.repair_base_checkpoint_id != last.last_verified_stable_snapshot_id
    assert last.candidate_checkpoint_id != last.stable_snapshot_id
    assert store.load(run.run_id).repair_attempts[-1].rollback_result == last.rollback_result
    assert run.target_branch is None


def test_invalid_failure_analysis_enters_model_error(tmp_path: Path) -> None:
    class InvalidFailureModel(RepairModel):
        def complete(self, component: str, payload: dict[str, Any],
                     schema: type[Any]) -> tuple[dict[str, Any], int, int]:
            if component == "Failure Analyzer":
                return {"failure_type": "missing required fields"}, 0, 0
            return super().complete(component, payload, schema)

    store = RunStore(tmp_path / "runs.db")
    workflow = Workflow(store, ModelClient(InvalidFailureModel(), store),
                        VerificationRunner(V2_PYTHON), repair_enabled=True)
    with pytest.raises(RuntimeError, match="invalid Failure Analyzer output"):
        workflow.run(FIXTURE, tmp_path / "artifacts", approval="APPROVE")
    with sqlite3.connect(store.path) as database:
        run_id = database.execute("SELECT run_id FROM runs").fetchone()[0]
    assert store.load(run_id).current_state == State.MODEL_ERROR
    assert store.history(run_id)[-1].next_state == State.MODEL_ERROR
    assert store.model_calls(run_id)[-1].error


def test_repair_cannot_weaken_regression_assertions() -> None:
    original = (FIXTURE / "tests/test_shop.py").read_text()
    weakened = original.replace('assert user.name == "Ada"', 'assert user.name == "Eve"')
    with Sandbox(FIXTURE) as sandbox:
        proposal = PatchProposal(changes=[FileChange(path="tests/test_shop.py",
                                                     content=weakened)], rationale="weaken test")
        with pytest.raises(ValueError, match="expectations changed"):
            apply_proposal(sandbox, proposal)
        assert sandbox.changed_files() == ()


def test_repair_path_traversal_is_rejected_before_write() -> None:
    with Sandbox(FIXTURE) as sandbox:
        proposal = PatchProposal(changes=[FileChange(
            path="src/../tests/test_shop.py", content="assert False\n")],
            rationale="unauthorized traversal")
        with pytest.raises(ValueError, match="traversal"):
            apply_proposal(sandbox, proposal)
        assert sandbox.changed_files() == ()


def test_degraded_attempt_two_restores_migration_candidate_then_attempt_three_passes(
        tmp_path: Path) -> None:
    model = RepairModel(repair_pass_on=2, degraded_on=1)
    run, store = _run(tmp_path, model)
    assert run.current_state == State.READY_FOR_PR
    assert run.attempt_number == 3 and model.repairs == 2
    first, second = run.repair_attempts
    assert first.degraded and first.rollback_target == first.repair_base_checkpoint_id
    assert first.repair_base_checkpoint_id is not None
    assert first.rollback_result == "restored " + first.repair_base_checkpoint_id
    assert first.rollback_reason == first.degraded_reason
    assert first.repair_base_checkpoint_id != first.last_verified_stable_snapshot_id
    assert second.repair_base_checkpoint_id == first.repair_base_checkpoint_id
    assert second.last_verified_stable_snapshot_id == first.last_verified_stable_snapshot_id
    assert second.verification_after and second.verification_after.passed
    assert run.patch and run.patch.post_snapshot == second.candidate_checkpoint_id
    assert store.load(run.run_id).repair_attempts[0].rollback_target == first.rollback_target
    states = _states(store, run.run_id)
    assert states.count(State.ANALYZING_FAILURE) == 2
    assert states[-1] == State.READY_FOR_PR


def test_failure_analyzer_context_exhaustion_escalates(tmp_path: Path) -> None:
    class NeedsContext(RepairModel):
        def complete(self, component: str, payload: dict[str, Any],
                     schema: type[Any]) -> tuple[dict[str, Any], int, int]:
            result, input_tokens, output_tokens = super().complete(component, payload, schema)
            if component == "Failure Analyzer":
                result["additional_context_needed"] = ["tests/test_shop.py"]
            return result, input_tokens, output_tokens

    model = NeedsContext()
    run, store = _run(tmp_path, model)
    assert run.current_state == State.NEEDS_HUMAN_REVIEW
    assert run.expansion_count == run.expansion_limit == 2
    assert len(run.context_expansions) == 2
    assert run.unresolved_context_request == ["tests/test_shop.py"]
    assert "Failure Analyzer" in (run.reason_for_escalation or "")
    assert store.history(run.run_id)[-1].previous_state == State.ANALYZING_FAILURE.value
    assert store.history(run.run_id)[-1].trigger == "context_expansion_exhausted"
    assert model.repairs == 0 and not run.repair_attempts
    assert State.REPAIR_APPROVED not in _states(store, run.run_id)
    assert store.load(run.run_id).reason_for_escalation == run.reason_for_escalation


def test_reviewer_context_exhaustion_escalates(tmp_path: Path) -> None:
    class ReviewerNeedsContext(RepairModel):
        def complete(self, component: str, payload: dict[str, Any],
                     schema: type[Any]) -> tuple[dict[str, Any], int, int]:
            result, input_tokens, output_tokens = super().complete(component, payload, schema)
            if component == "Change Reviewer":
                result["decision"] = "NEED_MORE_EVIDENCE"
                result["additional_context_needed"] = ["tests/test_shop.py"]
            return result, input_tokens, output_tokens

    model = ReviewerNeedsContext(ambiguous=True)
    run, store = _run(tmp_path, model)
    assert run.current_state == State.NEEDS_HUMAN_REVIEW
    assert run.expansion_count == run.expansion_limit == 2
    assert len(run.context_expansions) == 2 and model.reviews == 3
    assert run.unresolved_context_request == ["tests/test_shop.py"]
    assert "Reviewer" in (run.reason_for_escalation or "")
    assert store.history(run.run_id)[-1].previous_state == State.AWAITING_REVIEW.value
    assert store.history(run.run_id)[-1].trigger == "context_expansion_exhausted"
    assert model.repairs == 0 and not run.repair_attempts
    assert State.REPAIR_APPROVED not in _states(store, run.run_id)
    assert store.load(run.run_id).expansion_count == 2
