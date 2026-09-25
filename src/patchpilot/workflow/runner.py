"""Prompt 2 happy path and Prompt 3 bounded repair orchestrator."""

import hashlib
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import uuid
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal, TypeVar, cast

from pydantic.v1 import BaseModel

from patchpilot.sandbox import Sandbox

from .artifacts import export_run
from .benchmarks import declared_pin, dependency_verification_command, for_root
from .capability import (
    classify_request,
    failure_analysis_violation,
    plan_violation,
    proposal_violation,
    verification_capability,
    verification_failure_kind,
)
from .guardrails import build_allowed_scope, file_scope_reason, validate_test_change
from .model import ModelClient
from .persistence import PersistenceBoundary, PersistenceHalt
from .repair import (
    ChangeReviewer,
    FailureAnalyzer,
    RepairGenerator,
    degradation_reason,
    degraded,
    direct_approval_reason,
    failure_text,
    relevant_code,
    validate_analysis,
)
from .repository import analyze, capability, expand_context, select_context
from .schema import (
    AllowedModificationScope,
    ApprovalDecision,
    CapabilityClassification,
    ContextExpansionRecord,
    GuardrailViolation,
    MigrationPlan,
    MigrationRequest,
    PatchProposal,
    PatchResult,
    RepairAttemptRecord,
    RetryRecord,
    ReviewDecision,
    RunRecord,
    State,
    SystemFailureRecord,
    UnsupportedDecision,
    VerificationCheck,
    VerificationResult,
)
from .store import RunStore

T = TypeVar("T")
M = TypeVar("M", bound=BaseModel)


class WorkflowHalt(Exception):
    """A Prompt 5 system failure already recorded as a terminal run."""

def git(root: Path, *args: str) -> str:
    result = subprocess.run(["git", *args], cwd=root, text=True, capture_output=True, check=False)
    if result.returncode:
        raise RuntimeError(result.stderr or result.stdout)
    return result.stdout.strip()


def create_target(canonical: Path, parent: Path) -> Path:
    target = parent / "target"
    shutil.copytree(canonical, target, ignore=shutil.ignore_patterns(
        ".git", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", "*.egg-info"))
    git(target, "init", "-q", "-b", "main")
    git(target, "config", "user.name", "PatchPilot")
    git(target, "config", "user.email", "workflow@patchpilot.invalid")
    git(target, "add", "-A")
    git(target, "commit", "-qm", "Target baseline")
    return target


def apply_proposal(sandbox: Sandbox, proposal: PatchProposal,
                   scope: AllowedModificationScope | None = None) -> PatchResult:
    pre = sandbox.last_stable_snapshot
    if sandbox.changed_files():
        raise ValueError("sandbox must be clean before applying a proposal")
    if len({change.path for change in proposal.changes}) != len(proposal.changes):
        raise ValueError("duplicate patch path")
    family = for_root(sandbox.path)
    if family is None:
        raise ValueError("unsupported fixture dependency")
    if scope is None:
        scope = build_allowed_scope(sandbox.path, analyze(sandbox.path), family)
    for change in proposal.changes:
        reason = file_scope_reason(sandbox.path, scope, change.path)
        if reason:
            raise ValueError("patch path outside migration scope: " + reason)
        target = sandbox._safe_path(change.path)
        if scope.files[change.path].category == "test":
            validate_test_change(target.read_text(), change.content,
                                 family.allowed_test_api_rewrites)
    for change in proposal.changes:
        sandbox._safe_path(change.path).write_text(change.content)
    changed = list(sandbox.changed_files())
    if not changed or set(changed) != {change.path for change in proposal.changes}:
        raise ValueError("patch changes do not match proposal")
    diff = sandbox.diff()
    digest = hashlib.sha256(diff.encode()).hexdigest()
    post = sandbox.candidate_checkpoint("Sandbox migration proposal")
    return PatchResult(pre_snapshot=pre, post_snapshot=post,
                       changed_files=changed, diff=diff, sha256=digest)


class VerificationRunner:
    def __init__(self, python: Path = Path(sys.executable)) -> None:
        self.python = python.absolute()

    def run(self, root: Path) -> VerificationResult:
        family = for_root(root)
        if family is None:
            raise ValueError("unsupported fixture dependency")
        checks: list[VerificationCheck] = []
        dependencies = declared_pin(root, family)
        source = "\n".join(path.read_text() for folder in ("src", "tests")
                           for path in (root / folder).rglob("*.py"))
        migrated = (dependencies == family.target_pin and
                    not re.search(family.deprecated_api_pattern, source))
        checks.append(VerificationCheck(name=family.migration_check_name, command=[],
                                        exit_code=0 if migrated else 1,
                                        output="dependency and old API scan"))
        commands = [
            (family.dependency_check_name,
             dependency_verification_command(self.python, family)),
            ("pytest", [str(self.python), "-m", "pytest", "-q", "-p", "no:cacheprovider"]),
            ("mypy", [str(self.python), "-m", "mypy", "src", "tests"]),
            ("ruff", [str(self.python), "-m", "ruff", "check", "src", "tests"]),
            ("runtime/import", [str(self.python), "-c", family.runtime_check]),
        ]
        with tempfile.TemporaryDirectory(prefix="patchpilot-verification-cache-") as cache:
            environment = {**__import__("os").environ, "PYTHONPATH": "src",
                           "PYTHONDONTWRITEBYTECODE": "1",
                           "MYPY_CACHE_DIR": str(Path(cache) / "mypy"),
                           "RUFF_CACHE_DIR": str(Path(cache) / "ruff")}
            for name, command in commands:
                result = subprocess.run(command, cwd=root, text=True, capture_output=True,
                                        env=environment, check=False)
                checks.append(VerificationCheck(name=name, command=command,
                                                exit_code=result.returncode,
                                                output=result.stdout + result.stderr))
        return VerificationResult(passed=all(check.exit_code == 0 for check in checks),
                                  checks=checks)


class Workflow:
    def __init__(self, store: RunStore, client: ModelClient,
                 verifier: VerificationRunner, repair_enabled: bool = False,
                 max_context_expansions: int = 2,
                 benchmark_mode: bool = False) -> None:
        if max_context_expansions < 0:
            raise ValueError("context expansion limit cannot be negative")
        self.max_context_expansions = max_context_expansions
        self.benchmark_mode = benchmark_mode
        self.repair_enabled = repair_enabled
        self.store = PersistenceBoundary(store, lambda: self._prompt5)
        self.client = client
        self.client.store = self.store
        self.verifier = verifier

    def run(self, canonical: Path, artifact_parent: Path,
            approval: str = "APPROVE",
            request: MigrationRequest | None = None) -> RunRecord:
        self._active_run_id: str | None = None
        self._prompt5 = request is not None
        try:
            try:
                return self._run(canonical, artifact_parent, approval, request)
            except WorkflowHalt:
                assert self._active_run_id is not None
                return self.store.active_run or self.store.load(self._active_run_id)
            except Exception as exc:
                if self._active_run_id is not None:
                    failed = self.store.active_run or self.store.load(self._active_run_id)
                    terminal = {State.MODEL_ERROR, State.TOOL_ERROR, State.ENVIRONMENT_ERROR,
                                State.FAILED_SYSTEM, State.READY_FOR_PR, State.UNSUPPORTED,
                                State.NEEDS_HUMAN_REVIEW}
                    if self._prompt5 and failed.current_state not in terminal:
                        category = State.ENVIRONMENT_ERROR if isinstance(exc, OSError) else State.TOOL_ERROR
                        self._record_system_error(failed, category, "Orchestrator", exc, 1, False)
                        self.store.move(failed, category, type(exc).__name__, "Orchestrator")
                        self.store.move(failed, State.FAILED_SYSTEM, "unrecoverable_error", "Orchestrator")
                        failed.final_status = State.FAILED_SYSTEM.value
                        failed.terminal_reason = str(exc)
                        failed.ended_at = datetime.now(timezone.utc).isoformat()
                        self.store.save(failed)
                        return failed
                    if failed.current_state not in terminal:
                        error_state = State.ENVIRONMENT_ERROR if isinstance(exc, OSError) else State.TOOL_ERROR
                        self.store.move(failed, error_state, type(exc).__name__, "Orchestrator")
                        failed.final_status = error_state.value
                        failed.ended_at = datetime.now(timezone.utc).isoformat()
                        self.store.save(failed)
                raise
        except PersistenceHalt as exc:
            return exc.run
        finally:
            if self._active_run_id is not None:
                try:
                    export_run(self.store.raw, self._active_run_id, artifact_parent)
                except (sqlite3.Error, KeyError):
                    # A broken store cannot safely export itself; the run record and
                    # validated fallback transitions remain in memory.
                    pass

    def _record_system_error(self, run: RunRecord, category: State, component: str,
                             exc: Exception, attempt: int, recovered: bool) -> None:
        now = datetime.now(timezone.utc).isoformat()
        run.system_failures.append(SystemFailureRecord(
            component=component, category=cast(Literal["MODEL_ERROR", "TOOL_ERROR", "ENVIRONMENT_ERROR"], category.value),
            error_type=type(exc).__name__,
            error_message=str(exc), retry_count=attempt, recovered=False,
            timestamp=now))
        run.retries.append(RetryRecord(component=component, error_type=type(exc).__name__,
                                       retry_count=attempt, error_message=str(exc),
                                       recovered=False, timestamp=now))
        self.store.save(run)

    def _mark_recovered(self, run: RunRecord, start: int) -> None:
        if len(run.retries) == start:
            return
        for item in run.retries[start:]:
            item.recovered = True
        for failure_record in run.system_failures[start:]:
            failure_record.recovered = True
        self.store.save(run)

    def _model_failure_callback(self, run: RunRecord, component: str
                                ) -> Callable[[Exception, int, bool], None] | None:
        if not self._prompt5:
            return None
        previous = run.current_state

        def on_failure(exc: Exception, attempt: int, will_retry: bool) -> None:
            self._record_system_error(run, State.MODEL_ERROR, component, exc,
                                      attempt, will_retry)
            self.store.move(run, State.MODEL_ERROR, type(exc).__name__, component)
            if will_retry:
                self.store.move(run, previous, "model_retry", "Orchestrator")

        return on_failure

    def _call_model(self, run: RunRecord, component: str, payload: dict[str, object],
                    schema: type[M]) -> M:
        if not self._prompt5:
            return self.client.call(run.run_id, component, payload, schema)
        start = len(run.retries)
        try:
            result = self.client.call(run.run_id, component, payload, schema,
                                      on_failure=self._model_failure_callback(run, component))
            self._mark_recovered(run, start)
            return result
        except RuntimeError as exc:
            if run.current_state != State.MODEL_ERROR:
                self._record_system_error(run, State.MODEL_ERROR, component, exc, 1, False)
                self.store.move(run, State.MODEL_ERROR, type(exc).__name__, component)
            self.store.move(run, State.FAILED_SYSTEM, "model_retries_exhausted", "Orchestrator")
            run.final_status = State.FAILED_SYSTEM.value
            run.terminal_reason = str(exc)
            run.ended_at = datetime.now(timezone.utc).isoformat()
            self.store.save(run)
            raise WorkflowHalt from exc

    def _tool(self, run: RunRecord, component: str, action: Callable[[], T],
              category: State = State.TOOL_ERROR, retries: int = 1) -> T:
        if not self._prompt5:
            return action()
        previous = run.current_state
        start = len(run.retries)
        for attempt in range(1, retries + 2):
            try:
                result = action()
                self._mark_recovered(run, start)
                return result
            except (OSError, RuntimeError) as exc:
                retryable = attempt <= retries
                self._record_system_error(run, category, component, exc,
                                          attempt, retryable)
                self.store.move(run, category, type(exc).__name__, component)
                if retryable:
                    self.store.move(run, previous, "tool_recovered" if category == State.TOOL_ERROR
                                    else "environment_recovered", "Orchestrator")
                else:
                    self.store.move(run, State.FAILED_SYSTEM,
                                    "retries_exhausted", "Orchestrator")
                    run.final_status = State.FAILED_SYSTEM.value
                    run.terminal_reason = str(exc)
                    run.ended_at = datetime.now(timezone.utc).isoformat()
                    self.store.save(run)
                    raise WorkflowHalt from exc
        raise AssertionError("unreachable")

    def _scope_violation(self, run: RunRecord, violation: GuardrailViolation) -> RunRecord:
        run.guardrail_violations.append(violation)
        self.store.save(run)
        self.store.move(run, State.SCOPE_VIOLATION, violation.rule, violation.component)
        self.store.move(run, State.NEEDS_HUMAN_REVIEW,
                        "hard_scope_violation", "Orchestrator")
        run.final_status = State.NEEDS_HUMAN_REVIEW.value
        run.terminal_reason = violation.reason
        run.ended_at = datetime.now(timezone.utc).isoformat()
        self.store.save(run)
        return run

    def _model_or_error(self, run: RunRecord, call: Callable[[], T]) -> T:
        start = len(run.retries)
        try:
            result = call()
            if self._prompt5:
                self._mark_recovered(run, start)
            return result
        except RuntimeError as exc:
            if self._prompt5:
                if run.current_state != State.MODEL_ERROR:
                    self._record_system_error(run, State.MODEL_ERROR, "Model Client", exc, 1, False)
                    self.store.move(run, State.MODEL_ERROR, "invalid_model_output", "Model Client")
                self.store.move(run, State.FAILED_SYSTEM, "model_retries_exhausted", "Orchestrator")
                run.final_status = State.FAILED_SYSTEM.value
                run.terminal_reason = str(exc)
                run.ended_at = datetime.now(timezone.utc).isoformat()
                self.store.save(run)
                raise WorkflowHalt from exc
            self.store.move(run, State.MODEL_ERROR, "invalid_model_output", "Model Client")
            run.final_status = State.MODEL_ERROR.value
            run.ended_at = datetime.now(timezone.utc).isoformat()
            self.store.save(run)
            raise

    def _context_exhausted(self, run: RunRecord, requested: list[str],
                           reason: str, component: str) -> None:
        run.unresolved_context_request = requested
        run.reason_for_escalation = reason
        self.store.save(run)
        self.store.move(run, State.NEEDS_HUMAN_REVIEW,
                        "context_expansion_exhausted", component)
        run.final_status = State.NEEDS_HUMAN_REVIEW.value
        run.ended_at = datetime.now(timezone.utc).isoformat()
        self.store.save(run)

    def _repair_until_verified(self, run: RunRecord, sandbox: Sandbox) -> bool:
        assert run.plan is not None and run.analysis is not None
        assert run.context is not None and run.patch is not None
        assert run.sandbox_verification is not None
        family = for_root(sandbox.path)
        assert family is not None
        analyzer = FailureAnalyzer(self.client)
        reviewer = ChangeReviewer(self.client)
        generator = RepairGenerator(self.client)
        rejections = 0
        while True:
            before = run.sandbox_verification
            if run.attempt_number >= 3:
                self.store.move(run, State.NEEDS_HUMAN_REVIEW, "attempt_limit_reached", "Orchestrator")
                run.final_status = State.NEEDS_HUMAN_REVIEW.value
                run.ended_at = datetime.now(timezone.utc).isoformat()
                self.store.save(run)
                return False
            if run.current_state in (State.VERIFYING_SANDBOX, State.VERIFICATION_FAILURE):
                self.store.move(run, State.ANALYZING_FAILURE, "code_verification_failed", "Verification Runner")
            current_diff = git(sandbox.path, "diff", sandbox.original_snapshot, "HEAD")
            affected = list(dict.fromkeys([*run.patch.changed_files,
                                           *(run.plan.affected_files if run.plan else [])]))
            original_code = {name: sandbox.original_file(name)[:12000] for name in affected
                             if (sandbox.path / name).is_file()}
            payload: dict[str, object] = {
                "migration_goal": run.request.migration_goal,
                "migration_plan": run.plan.dict(), "attempt_number": run.attempt_number,
                "current_diff": current_diff,
                "original_relevant_code": original_code,
                "current_relevant_code": relevant_code(sandbox.path, affected),
                "failing_tests_stdout_stderr_stack_trace": failure_text(before),
                "verification_result": before.dict(),
                "previous_attempts": [item.dict() for item in run.repair_attempts],
                "selected_context": [item.dict() for item in run.context.items],
                "context_files": [item.path for item in run.context.items],
            }
            analyzer_retry_start = len(run.retries)
            try:
                analysis = analyzer.analyze(run.run_id, payload,
                                            self._model_failure_callback(run, "Failure Analyzer"))
                validate_analysis(analysis)
                if self._prompt5:
                    self._mark_recovered(run, analyzer_retry_start)
                run.failure_analyses.append(analysis)
                self.store.save(run)
            except WorkflowHalt:
                raise
            except (RuntimeError, ValueError) as exc:
                if self._prompt5:
                    if run.current_state != State.MODEL_ERROR:
                        self._record_system_error(run, State.MODEL_ERROR,
                                                  "Failure Analyzer", exc, 1, False)
                        self.store.move(run, State.MODEL_ERROR,
                                        "invalid_failure_analysis", "Model Client")
                    self.store.move(run, State.FAILED_SYSTEM,
                                    "model_retries_exhausted", "Orchestrator")
                    run.final_status = State.FAILED_SYSTEM.value
                    run.terminal_reason = str(exc)
                    run.ended_at = datetime.now(timezone.utc).isoformat()
                    self.store.save(run)
                    raise WorkflowHalt from exc
                if run.current_state != State.MODEL_ERROR:
                    self.store.move(run, State.MODEL_ERROR, "invalid_failure_analysis", "Model Client")
                    run.final_status = State.MODEL_ERROR.value
                    run.ended_at = datetime.now(timezone.utc).isoformat()
                    self.store.save(run)
                raise
            repair_scope = build_allowed_scope(sandbox.path, run.analysis, family,
                run.plan, tuple(analysis.files_to_modify), failure_text(before))
            if self._prompt5:
                violation = failure_analysis_violation(sandbox.path, analysis, repair_scope)
                if violation is not None:
                    self._scope_violation(run, violation)
                    return False
            if analysis.additional_context_needed and run.expansion_count >= run.expansion_limit:
                self._context_exhausted(run, analysis.additional_context_needed,
                                        "Failure Analyzer requested evidence after expansion limit",
                                        "Failure Analyzer")
                return False
            self.store.move(run, State.REPAIR_PROPOSED, "failure_analyzed", "Failure Analyzer")
            if analysis.additional_context_needed:
                self.store.move(run, State.GATHERING_ADDITIONAL_CONTEXT,
                                "analysis_requested_context", "Context Manager")
                previous = run.context
                run.context = expand_context(sandbox.path, run.analysis, previous,
                                             failure_text(before), run.patch.changed_files,
                                             analysis.additional_context_needed)
                run.context_expansions.append(ContextExpansionRecord(
                    attempt_number=run.attempt_number, previous_context=previous,
                    new_context=run.context,
                    expansion_reason="Failure Analyzer requested: " +
                                     ", ".join(analysis.additional_context_needed)))
                self.store.save(run)
                run.expansion_count += 1
                self.store.save(run)
                self.store.move(run, State.ANALYZING_FAILURE,
                                "context_expanded", "Context Manager")
                continue
            direct_reason = direct_approval_reason(sandbox.path, analysis, run.plan, before, run.analysis)
            path = "deterministic" if direct_reason else "reviewer"
            decisions = []
            if direct_reason:
                run.repair_decisions.append("deterministic: " + direct_reason)
                self.store.save(run)
                self.store.move(run, State.REPAIR_APPROVED, "objective_evidence", "Orchestrator")
            else:
                self.store.move(run, State.AWAITING_REVIEW, "ambiguous_scope", "Orchestrator")
                for review_round in range(run.expansion_limit + 1):
                    review_payload: dict[str, object] = {
                        **payload, "failure_analysis": analysis.dict(),
                        "requested_files": analysis.files_to_modify,
                        "selected_context": [item.dict() for item in run.context.items],
                    }
                    def review_call(payload: dict[str, object] = review_payload) -> ReviewDecision:
                        return reviewer.review(run.run_id, payload,
                                               self._model_failure_callback(run, "Change Reviewer"))

                    decision = self._model_or_error(run, review_call)
                    decisions.append(decision)
                    run.review_history.append(decision)
                    self.store.save(run)
                    if decision.decision == "APPROVE":
                        run.repair_decisions.append("reviewer: " + decision.reason)
                        self.store.save(run)
                        self.store.move(run, State.REPAIR_APPROVED,
                                        "reviewer_approved", "Change Reviewer")
                        break
                    if decision.decision == "REJECT":
                        run.repair_decisions.append("rejected: " + decision.reason)
                        self.store.save(run)
                        self.store.move(run, State.REPAIR_REJECTED,
                                        "reviewer_rejected", "Change Reviewer")
                        rejections += 1
                        if rejections < 2:
                            self.store.move(run, State.ANALYZING_FAILURE,
                                            "alternate_strategy_requested", "Orchestrator")
                            break
                        self.store.move(run, State.NEEDS_HUMAN_REVIEW,
                                        "no_supported_repair", "Orchestrator")
                        run.final_status = State.NEEDS_HUMAN_REVIEW.value
                        run.ended_at = datetime.now(timezone.utc).isoformat()
                        self.store.save(run)
                        return False
                    if run.expansion_count >= run.expansion_limit:
                        self._context_exhausted(run, decision.additional_context_needed,
                                                "Reviewer requested evidence after expansion limit",
                                                "Change Reviewer")
                        return False
                    self.store.move(run, State.GATHERING_ADDITIONAL_CONTEXT,
                                    "reviewer_requested_evidence", "Context Manager")
                    previous = run.context
                    run.context = expand_context(sandbox.path, run.analysis, previous,
                                                 failure_text(before), run.patch.changed_files,
                                                 decision.additional_context_needed)
                    run.context_expansions.append(ContextExpansionRecord(
                        attempt_number=run.attempt_number, previous_context=previous,
                        new_context=run.context,
                        expansion_reason="Reviewer requested: " +
                                         ", ".join(decision.additional_context_needed)))
                    self.store.save(run)
                    run.expansion_count += 1
                    self.store.save(run)
                    self.store.move(run, State.AWAITING_REVIEW,
                                    "context_expanded", "Context Manager")
                if run.current_state == State.ANALYZING_FAILURE:
                    continue
                if run.current_state == State.AWAITING_REVIEW:
                    self.store.move(run, State.REPAIR_REJECTED,
                                    "review_limit_reached", "Orchestrator")
                    self.store.move(run, State.NEEDS_HUMAN_REVIEW,
                                    "review_limit_reached", "Orchestrator")
                    run.final_status = State.NEEDS_HUMAN_REVIEW.value
                    run.ended_at = datetime.now(timezone.utc).isoformat()
                    self.store.save(run)
                    return False
            next_attempt = run.attempt_number + 1
            record = RepairAttemptRecord(
                attempt_number=next_attempt, failure_analysis=analysis,
                repair_decision_path=path, approval_reason=direct_reason or
                "independent Reviewer approved", reviewer_decisions=decisions,
                stable_snapshot_id=sandbox.last_stable_snapshot,
                last_verified_stable_snapshot_id=sandbox.last_stable_snapshot,
                repair_base_checkpoint_id=git(sandbox.path, "rev-parse", "HEAD"),
                verification_before=before)
            run.repair_attempts.append(record)
            run.attempt_number = next_attempt
            self.store.save(run)
            self.store.move(run, State.REPAIRING, "repair_authorized", "Orchestrator")
            repair_payload: dict[str, object] = {
                "migration_goal": run.request.migration_goal,
                "migration_plan": run.plan.dict(), "attempt_number": next_attempt,
                "failure_analysis": analysis.dict(), "approved_files": analysis.files_to_modify,
                "current_relevant_code": relevant_code(sandbox.path, analysis.files_to_modify),
                "current_diff": current_diff, "verification_result": before.dict(),
                "selected_context": [item.dict() for item in run.context.items],
                "context_files": [item.path for item in run.context.items],
            }
            def repair_call(payload: dict[str, object] = repair_payload) -> PatchProposal:
                return generator.generate(run.run_id, payload,
                                          self._model_failure_callback(run, "Repair Generator"))

            repair = self._model_or_error(run, repair_call)
            record.proposal = repair
            changed = {item.path for item in repair.changes}
            if not changed or not changed.issubset(set(analysis.files_to_modify)):
                if self._prompt5:
                    self._scope_violation(run, GuardrailViolation(
                        rule="approved_repair_scope", reason="repair includes unapproved files",
                        component="Repair Generator"))
                    return False
                raise ValueError("repair patch includes unapproved files")
            if self._prompt5:
                violation = proposal_violation(sandbox.path, repair, "Repair Generator",
                                               repair_scope, family.allowed_test_api_rewrites,
                                               run.guardrail_decisions)
                self.store.save(run)
                if violation is not None:
                    self._scope_violation(run, violation)
                    return False
            def apply_repair(proposal: PatchProposal = repair,
                             approved_scope: AllowedModificationScope = repair_scope) -> PatchResult:
                return apply_proposal(sandbox, proposal, approved_scope)

            candidate = self._tool(run, "Repair Executor", apply_repair, retries=0)
            record.candidate_checkpoint_id = candidate.post_snapshot
            record.repair_diff = candidate.diff
            self.store.save(run)
            self.store.move(run, State.VERIFYING_SANDBOX, "repair_candidate_applied", "Repair Executor")
            after = self._tool(run, "Verification Runner",
                               lambda: self.verifier.run(sandbox.path),
                               State.ENVIRONMENT_ERROR)
            record.verification_after = after
            run.sandbox_verification = after
            self.store.save(run)
            if not after.passed and self._prompt5:
                family = for_root(sandbox.path)
                assert family is not None
                kind = verification_failure_kind(after, family.dependency_check_name)
                run.failure_classification = kind
                self.store.save(run)
                if kind == "ENVIRONMENT_ERROR":
                    self._record_system_error(
                        run, State.ENVIRONMENT_ERROR, "Verification Runner",
                        RuntimeError("repair verification check could not run"), 1, False)
                    self.store.move(run, State.ENVIRONMENT_ERROR,
                                    "repair_verification_environment_failed", "Verification Runner")
                    self.store.move(run, State.FAILED_SYSTEM,
                                    "environment_unrecoverable", "Orchestrator")
                    run.final_status = State.FAILED_SYSTEM.value
                    run.terminal_reason = "repair verification environment failed"
                    run.ended_at = datetime.now(timezone.utc).isoformat()
                    self.store.save(run)
                    return False
            if after.passed:
                sandbox.promote_candidate(candidate.post_snapshot)
                cumulative = subprocess.run(
                    ["git", "diff", sandbox.original_snapshot, "HEAD"], cwd=sandbox.path,
                    text=True, capture_output=True, check=True).stdout
                files = git(sandbox.path, "diff", "--name-only", sandbox.original_snapshot,
                            "HEAD").splitlines()
                run.patch = PatchResult(pre_snapshot=sandbox.original_snapshot,
                                        post_snapshot=candidate.post_snapshot,
                                        changed_files=files, diff=cumulative,
                                        sha256=hashlib.sha256(cumulative.encode()).hexdigest())
                self.store.save(run)
                self.store.move(run, State.VERIFIED_PATCH_READY,
                                "repair_checks_passed", "Verification Runner")
                return True
            if degraded(before, after):
                record.degraded = True
                record.degraded_reason = degradation_reason(before, after)
                record.rollback_target = record.repair_base_checkpoint_id
                record.rollback_reason = record.degraded_reason
                assert record.rollback_target is not None
                restored = sandbox.restore_checkpoint(record.rollback_target)
                record.rollback_result = "restored " + restored
                self.store.save(run)
            if self._prompt5:
                self.store.move(run, State.VERIFICATION_FAILURE,
                                "repair_migration_check_failed", "Verification Runner")
            if run.attempt_number == 3:
                self.store.move(run, State.NEEDS_HUMAN_REVIEW,
                                "attempt_limit_reached", "Orchestrator")
                run.final_status = State.NEEDS_HUMAN_REVIEW.value
                run.ended_at = datetime.now(timezone.utc).isoformat()
                self.store.save(run)
                return False
            self.store.move(run, State.ANALYZING_FAILURE,
                            "repair_verification_failed", "Verification Runner")

    def _run(self, canonical: Path, artifact_parent: Path,
             approval: str, request_override: MigrationRequest | None = None) -> RunRecord:
        canonical = canonical.resolve(strict=True)
        artifact_parent.mkdir(parents=True, exist_ok=True)
        target = artifact_parent / "target"
        if not self._prompt5:
            target = create_target(canonical, artifact_parent)
        family = for_root(canonical)
        if family is None:
            raise ValueError("unsupported fixture dependency")
        request = request_override or MigrationRequest(repository=str(target),
                                                       migration_goal=family.goal)
        benchmark = self.benchmark_mode
        run = RunRecord(run_id=uuid.uuid4().hex, request=request,
                        current_state=State.RECEIVED,
                        expansion_limit=self.max_context_expansions,
                        prompt_name=("05_guardrails_failures" if self._prompt5 else
                                     "04_remaining_use_cases" if benchmark else
                                     "03_failure_repair_path" if self.repair_enabled else
                                     "02_happy_path_e2e"),
                        prompt_version=("v1" if self._prompt5 else "v1.1" if benchmark
                                        else "v1" if self.repair_enabled else "v1.1"),
                        use_case=family.use_case, migration_family=family.name,
                        model_type=("live" if getattr(self.client.backend, "model", "") ==
                                    "gpt-5.6-sol" else "test_double"),
                        repository_identifiers={"canonical": str(canonical),
                                                "migration_family": family.name,
                                                "use_case": str(family.use_case),
                                                "target": str(target),
                                                "target_main_commit": "" if self._prompt5 else
                                                git(target, "rev-parse", "main")},
                        started_at=datetime.now(timezone.utc).isoformat())
        self._active_run_id = run.run_id
        self.store.save(run)
        self.store.move(run, State.RECEIVED, "request_created", "Orchestrator")
        self.store.move(run, State.SCOPE_CHECK, "begin_capability_check", "Orchestrator")
        if self._prompt5:
            scope, unsupported = classify_request(request, (canonical, target))
            run.scope_rule = scope
            if unsupported is not None:
                run.unsupported_decision = unsupported
                self.store.save(run)
                self.store.move(run, State.UNSUPPORTED, unsupported.violated_scope_rule,
                                "Capability Gate")
                run.final_status = State.UNSUPPORTED.value
                run.terminal_reason = unsupported.reason
                run.ended_at = datetime.now(timezone.utc).isoformat()
                self.store.save(run)
                return run
            if scope == "AMBIGUOUS":
                self.store.move(run, State.CAPABILITY_CLASSIFYING,
                                "semantic_scope_ambiguous", "Capability Gate")
                classification = self._call_model(run, "CapabilityClassifier", {
                    "request": request.dict(), "supported_migration": family.goal,
                    "repository_family": family.name,
                }, CapabilityClassification)
                run.capability_classification = classification
                self.store.save(run)
                if classification.classification == "UNSUPPORTED":
                    run.unsupported_decision = UnsupportedDecision(
                        reason=classification.reason,
                        detected_request_type=classification.detected_migration_type,
                        violated_scope_rule="semantic_classification")
                    self.store.save(run)
                    self.store.move(run, State.UNSUPPORTED, "classifier_unsupported",
                                    "CapabilityClassifier")
                    run.final_status = State.UNSUPPORTED.value
                    run.terminal_reason = classification.reason
                    run.ended_at = datetime.now(timezone.utc).isoformat()
                    self.store.save(run)
                    return run
                if (classification.classification == "SUPPORTED_MIGRATION" and
                        classification.detected_migration_type.lower() not in
                        (family.name.lower(), family.goal.lower())):
                    self.store.move(run, State.NEEDS_HUMAN_REVIEW,
                                    "classified_migration_mismatch", "CapabilityClassifier")
                    run.final_status = State.NEEDS_HUMAN_REVIEW.value
                    run.terminal_reason = "classified migration does not match repository family"
                    run.ended_at = datetime.now(timezone.utc).isoformat()
                    self.store.save(run)
                    return run
                if classification.classification == "NEED_MORE_INFORMATION":
                    self.store.move(run, State.NEEDS_HUMAN_REVIEW,
                                    "classifier_needs_information", "CapabilityClassifier")
                    run.final_status = State.NEEDS_HUMAN_REVIEW.value
                    run.terminal_reason = classification.reason
                    run.ended_at = datetime.now(timezone.utc).isoformat()
                    self.store.save(run)
                    return run
            elif family.goal != request.migration_goal:
                run.unsupported_decision = UnsupportedDecision(
                    reason="requested migration does not match repository family",
                    detected_request_type="different_migration_family",
                    violated_scope_rule="fixed_family_repository_match")
                self.store.save(run)
                self.store.move(run, State.UNSUPPORTED,
                                "migration_family_mismatch", "Capability Gate")
                run.final_status = State.UNSUPPORTED.value
                run.terminal_reason = run.unsupported_decision.reason
                run.ended_at = datetime.now(timezone.utc).isoformat()
                self.store.save(run)
                return run
            self.store.move(run, State.VERIFICATION_CAPABILITY_CHECK,
                            "scope_supported", "Capability Gate")
            self._tool(run, "Target Repository", lambda: create_target(canonical, artifact_parent),
                       State.ENVIRONMENT_ERROR, retries=0)
            run.repository_identifiers["target_main_commit"] = git(target, "rev-parse", "main")
            self.store.save(run)
            verification_request = MigrationRequest(repository=str(target),
                                                    migration_goal=family.goal)
            decision = capability(verification_request, target, self.verifier.python)
            run.capability_decision = decision
            run.verification_capability = verification_capability(
                target, family, decision.reasons)
            self.store.save(run)
            if not run.verification_capability.sufficient or not decision.supported:
                if ("target dependency unavailable in verification environment" in decision.reasons
                        or "verification Python unavailable" in decision.reasons):
                    reason = "required verification environment unavailable"
                    self._record_system_error(run, State.ENVIRONMENT_ERROR,
                                              "Capability Gate", RuntimeError(reason), 1, False)
                    self.store.move(run, State.ENVIRONMENT_ERROR,
                                    "target_dependency_unavailable", "Capability Gate")
                    self.store.move(run, State.FAILED_SYSTEM,
                                    "environment_unrecoverable", "Orchestrator")
                    run.final_status = State.FAILED_SYSTEM.value
                else:
                    reason = "cannot safely verify migration"
                    self.store.move(run, State.NEEDS_HUMAN_REVIEW,
                                    "verification_insufficient", "Capability Gate")
                    run.final_status = State.NEEDS_HUMAN_REVIEW.value
                run.terminal_reason = reason + ": " + ", ".join(
                    run.verification_capability.reasons or decision.reasons)
                run.ended_at = datetime.now(timezone.utc).isoformat()
                self.store.save(run)
                return run
            self.store.move(run, State.ANALYZING_REPO, "verification_capable",
                            "Capability Gate")
        else:
            decision = capability(request, target, self.verifier.python)
            run.capability_decision = decision
            self.store.save(run)
            if not decision.supported:
                if "target dependency unavailable in verification environment" in decision.reasons:
                    self.store.move(run, State.ENVIRONMENT_ERROR,
                                    "target_dependency_unavailable", "Capability Gate")
                    run.final_status = State.ENVIRONMENT_ERROR.value
                    run.ended_at = datetime.now(timezone.utc).isoformat()
                    self.store.save(run)
                    return run
                raise ValueError(decision.reasons)
            self.store.move(run, State.ANALYZING_REPO, "supported", "Capability Gate")
        run.analysis = self._tool(run, "Repository Analyzer", lambda: analyze(target))
        self.store.save(run)
        self.store.move(run, State.CONTEXT_BUILDING, "analysis_complete", "Repository Analyzer")
        analysis_result = run.analysis
        assert analysis_result is not None
        run.context = self._tool(run, "Context Manager",
                                 lambda: select_context(target, analysis_result))
        self.store.save(run)
        self.store.move(run, State.PLANNING, "context_selected", "Context Manager")
        payload: dict[str, object] = {"request": request.dict(), "analysis": run.analysis.dict(),
                   "context": [item.dict() for item in run.context.items],
                   "context_files": [item.path for item in run.context.items]}
        try:
            run.plan = self._call_model(run, "Migration Planner", payload, MigrationPlan)
        except RuntimeError:
            self.store.move(run, State.MODEL_ERROR, "invalid_model_output", "Model Client")
            run.final_status = State.MODEL_ERROR.value
            run.ended_at = datetime.now(timezone.utc).isoformat()
            self.store.save(run)
            raise
        self.store.save(run)
        if self._prompt5:
            eligible_scope = build_allowed_scope(target, run.analysis, family)
            violation = plan_violation(target, run.plan, eligible_scope,
                                       run.guardrail_decisions)
            self.store.save(run)
            if violation is not None:
                return self._scope_violation(run, violation)
        migration_scope = build_allowed_scope(target, run.analysis, family, run.plan)
        run.allowed_modification_scope = migration_scope
        self.store.save(run)
        self.store.move(run, State.PATCH_GENERATING, "plan_validated", "Migration Planner")
        try:
            proposal = self._call_model(run, "Patch Generator", {
                "plan": run.plan.dict(), "context": payload["context"],
                "context_files": payload["context_files"], "constraints": request.constraints,
            }, PatchProposal)
        except RuntimeError:
            self.store.move(run, State.MODEL_ERROR, "invalid_model_output", "Model Client")
            run.final_status = State.MODEL_ERROR.value
            run.ended_at = datetime.now(timezone.utc).isoformat()
            self.store.save(run)
            raise
        run.proposal = proposal
        self.store.save(run)
        if self._prompt5:
            violation = proposal_violation(target, proposal, "Patch Generator", migration_scope,
                                           family.allowed_test_api_rewrites,
                                           run.guardrail_decisions)
            self.store.save(run)
            if violation is not None:
                return self._scope_violation(run, violation)
        self.store.move(run, State.PATCHING_SANDBOX, "proposal_validated", "Patch Generator")
        sandbox_copy = self._tool(run, "Sandbox", lambda: Sandbox(target),
                                  State.ENVIRONMENT_ERROR, retries=0)
        with sandbox_copy as sandbox:
            run.patch = self._tool(run, "Patch Tool",
                                   lambda: apply_proposal(sandbox, proposal, migration_scope), retries=0)
            bundle = artifact_parent / "sandbox-snapshot.bundle"
            self._tool(run, "Git snapshot",
                       lambda: git(sandbox.path, "bundle", "create", str(bundle), "HEAD"))
            run.repository_identifiers["sandbox_bundle"] = str(bundle)
            self.store.save(run)
            self.store.move(run, State.VERIFYING_SANDBOX, "sandbox_patch_applied", "Patch Tool")
            run.sandbox_verification = self._tool(
                run, "Verification Runner", lambda: self.verifier.run(sandbox.path),
                State.ENVIRONMENT_ERROR)
            self.store.save(run)
            if not run.sandbox_verification.passed:
                failure_kind = verification_failure_kind(run.sandbox_verification,
                                                         family.dependency_check_name)
                run.failure_classification = failure_kind
                self.store.save(run)
                if failure_kind == "ENVIRONMENT_ERROR":
                    if self._prompt5:
                        self._record_system_error(
                            run, State.ENVIRONMENT_ERROR, "Verification Runner",
                            RuntimeError("required verification check could not run"), 1, False)
                    self.store.move(run, State.ENVIRONMENT_ERROR,
                                    "verification_environment_failed", "Verification Runner")
                    if self._prompt5:
                        self.store.move(run, State.FAILED_SYSTEM,
                                        "environment_unrecoverable", "Orchestrator")
                    run.final_status = run.current_state.value
                    run.terminal_reason = "verification environment could not run required checks"
                    run.ended_at = datetime.now(timezone.utc).isoformat()
                    self.store.save(run)
                    return run
                if self._prompt5:
                    self.store.move(run, State.VERIFICATION_FAILURE,
                                    "migration_check_failed", "Verification Runner")
                if not self.repair_enabled:
                    if self._prompt5:
                        self.store.move(run, State.NEEDS_HUMAN_REVIEW,
                                        "repair_disabled", "Orchestrator")
                        run.final_status = State.NEEDS_HUMAN_REVIEW.value
                    else:
                        run.final_status = "sandbox_verification_failed"
                    run.ended_at = datetime.now(timezone.utc).isoformat()
                    self.store.save(run)
                    return run
                if not self._repair_until_verified(run, sandbox):
                    return run
                self._tool(run, "Git snapshot",
                           lambda: git(sandbox.path, "bundle", "create", str(bundle), "--all"))
            else:
                sandbox.promote_candidate(run.patch.post_snapshot)
                self.store.move(run, State.VERIFIED_PATCH_READY, "checks_passed", "Verification Runner")
            self.store.move(run, State.AWAITING_APPROVAL, "approval_requested", "Orchestrator")
            run.approval = ApprovalDecision(decision=approval, actor="simulated-human",
                                            timestamp=datetime.now(timezone.utc).isoformat())
            self.store.save(run)
            if approval != "APPROVE":
                run.final_status = "approval_declined"
                run.ended_at = datetime.now(timezone.utc).isoformat()
                self.store.save(run)
                return run
            self.store.move(run, State.APPROVED, "approved", "Simulated Human")
            self.store.move(run, State.APPLYING_TO_TARGET_BRANCH, "apply_authorized", "Orchestrator")
            branch = f"patchpilot/{family.branch_slug}-{run.run_id[:8]}"
            patch_file = artifact_parent / "verified.patch"
            verified_patch = run.patch
            assert verified_patch is not None
            patch_file.write_text(verified_patch.diff)

            def apply_verified_target() -> None:
                git(target, "switch", "-c", branch)
                git(target, "apply", "--check", str(patch_file))
                git(target, "apply", str(patch_file))
                applied = subprocess.run(["git", "diff"], cwd=target, text=True,
                                         capture_output=True, check=True).stdout
                if applied != verified_patch.diff:
                    raise RuntimeError("target diff differs from sandbox verified diff")
                git(target, "add", "-A")
                git(target, "commit", "-qm",
                    f"Apply verified {family.commit_label} migration patch")

            self._tool(run, "Target Patch Tool", apply_verified_target, retries=0)
            run.target_branch = branch
            run.repository_identifiers["target_commit"] = git(target, "rev-parse", "HEAD")
            self.store.save(run)
            self.store.move(run, State.VERIFYING_TARGET_BRANCH, "exact_patch_applied", "Patch Tool")
            run.target_verification = self._tool(
                run, "Verification Runner", lambda: self.verifier.run(target),
                State.ENVIRONMENT_ERROR)
            self.store.save(run)
            if not run.target_verification.passed:
                if self._prompt5:
                    kind = verification_failure_kind(run.target_verification,
                                                     family.dependency_check_name)
                    run.failure_classification = kind
                    if kind == "ENVIRONMENT_ERROR":
                        self._record_system_error(
                            run, State.ENVIRONMENT_ERROR, "Verification Runner",
                            RuntimeError("target verification check could not run"), 1, False)
                        self.store.move(run, State.ENVIRONMENT_ERROR,
                                        "target_environment_failed", "Verification Runner")
                        self.store.move(run, State.FAILED_SYSTEM,
                                        "environment_unrecoverable", "Orchestrator")
                    else:
                        self.store.move(run, State.VERIFICATION_FAILURE,
                                        "target_migration_check_failed", "Verification Runner")
                        self.store.move(run, State.NEEDS_HUMAN_REVIEW,
                                        "target_verification_failed", "Orchestrator")
                    run.final_status = run.current_state.value
                else:
                    run.final_status = "target_verification_failed"
            else:
                self.store.move(run, State.READY_FOR_PR, "checks_passed", "Verification Runner")
                run.final_status = State.READY_FOR_PR.value
            run.ended_at = datetime.now(timezone.utc).isoformat()
            self.store.save(run)
        return run
