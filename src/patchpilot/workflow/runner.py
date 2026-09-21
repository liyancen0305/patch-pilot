"""Prompt 2 happy path and Prompt 3 bounded repair orchestrator."""

import hashlib
import re
import shutil
import subprocess
import sys
import tempfile
import uuid
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import TypeVar

from patchpilot.sandbox import Sandbox

from .artifacts import export_run
from .guardrails import validate_test_change
from .model import ModelClient
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
    ApprovalDecision,
    ContextExpansionRecord,
    MigrationPlan,
    MigrationRequest,
    PatchProposal,
    PatchResult,
    RepairAttemptRecord,
    ReviewDecision,
    RunRecord,
    State,
    VerificationCheck,
    VerificationResult,
)
from .store import RunStore

T = TypeVar("T")

V1_SOURCE = re.compile(r"@(?:root_validator|validator)\b|class Config\b|\.parse_obj\(|\.dict\(")


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


def apply_proposal(sandbox: Sandbox, proposal: PatchProposal) -> PatchResult:
    pre = sandbox.last_stable_snapshot
    if sandbox.changed_files():
        raise ValueError("sandbox must be clean before applying a proposal")
    if len({change.path for change in proposal.changes}) != len(proposal.changes):
        raise ValueError("duplicate patch path")
    for change in proposal.changes:
        parts = PurePosixPath(change.path)
        if parts.is_absolute() or ".." in parts.parts or "." in parts.parts:
            raise ValueError("patch path traversal is forbidden")
        if not change.path.startswith(("src/", "tests/")) and change.path != "pyproject.toml":
            raise ValueError("patch path outside migration scope")
        target = sandbox._safe_path(change.path)
        if not target.is_file() or target.is_symlink():
            raise ValueError("patch must modify an existing regular file")
        if change.path.startswith("tests/"):
            validate_test_change(target.read_text(), change.content)
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
        checks: list[VerificationCheck] = []
        dependencies = (root / "pyproject.toml").read_text()
        source = "\n".join(path.read_text() for folder in ("src", "tests")
                           for path in (root / folder).rglob("*.py"))
        migrated = bool(re.search(r"pydantic(?:>=|==)2", dependencies)) and not V1_SOURCE.search(source)
        checks.append(VerificationCheck(name="Pydantic v2 migration", command=[],
                                        exit_code=0 if migrated else 1,
                                        output="dependency and v1 API scan"))
        commands = [
            ("installed Pydantic v2", [str(self.python), "-c", "import pydantic; assert int(pydantic.VERSION.split('.')[0]) == 2"]),
            ("pytest", [str(self.python), "-m", "pytest", "-q", "-p", "no:cacheprovider"]),
            ("mypy", [str(self.python), "-m", "mypy", "src", "tests"]),
            ("ruff", [str(self.python), "-m", "ruff", "check", "src", "tests"]),
            ("runtime/import", [str(self.python), "-c", "import shop; assert shop.User and shop.Order"]),
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
                 max_context_expansions: int = 2) -> None:
        if max_context_expansions < 0:
            raise ValueError("context expansion limit cannot be negative")
        self.max_context_expansions = max_context_expansions
        self.repair_enabled = repair_enabled
        self.store = store
        self.client = client
        self.verifier = verifier

    def run(self, canonical: Path, artifact_parent: Path,
            approval: str = "APPROVE") -> RunRecord:
        self._active_run_id: str | None = None
        try:
            return self._run(canonical, artifact_parent, approval)
        except Exception as exc:
            if self._active_run_id is not None:
                failed = self.store.load(self._active_run_id)
                terminal = {State.MODEL_ERROR, State.TOOL_ERROR, State.ENVIRONMENT_ERROR,
                            State.FAILED_SYSTEM, State.READY_FOR_PR}
                if failed.current_state not in terminal:
                    error_state = State.ENVIRONMENT_ERROR if isinstance(exc, OSError) else State.TOOL_ERROR
                    self.store.move(failed, error_state, type(exc).__name__, "Orchestrator")
                    failed.final_status = error_state.value
                    failed.ended_at = datetime.now(timezone.utc).isoformat()
                    self.store.save(failed)
            raise
        finally:
            if self._active_run_id is not None:
                export_run(self.store, self._active_run_id, artifact_parent)

    def _model_or_error(self, run: RunRecord, call: Callable[[], T]) -> T:
        try:
            return call()
        except RuntimeError:
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
            if run.current_state == State.VERIFYING_SANDBOX:
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
            try:
                analysis = analyzer.analyze(run.run_id, payload)
                validate_analysis(analysis)
                run.failure_analyses.append(analysis)
                self.store.save(run)
            except (RuntimeError, ValueError):
                if run.current_state != State.MODEL_ERROR:
                    self.store.move(run, State.MODEL_ERROR, "invalid_failure_analysis", "Model Client")
                    run.final_status = State.MODEL_ERROR.value
                    run.ended_at = datetime.now(timezone.utc).isoformat()
                    self.store.save(run)
                raise
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
                        return reviewer.review(run.run_id, payload)

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
                return generator.generate(run.run_id, payload)

            repair = self._model_or_error(run, repair_call)
            record.proposal = repair
            changed = {item.path for item in repair.changes}
            if not changed or not changed.issubset(set(analysis.files_to_modify)):
                raise ValueError("repair patch includes unapproved files")
            candidate = apply_proposal(sandbox, repair)
            record.candidate_checkpoint_id = candidate.post_snapshot
            record.repair_diff = candidate.diff
            self.store.save(run)
            self.store.move(run, State.VERIFYING_SANDBOX, "repair_candidate_applied", "Repair Executor")
            after = self.verifier.run(sandbox.path)
            record.verification_after = after
            run.sandbox_verification = after
            self.store.save(run)
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
             approval: str) -> RunRecord:
        canonical = canonical.resolve(strict=True)
        artifact_parent.mkdir(parents=True, exist_ok=True)
        target = create_target(canonical, artifact_parent)
        request = MigrationRequest(repository=str(target))
        run = RunRecord(run_id=uuid.uuid4().hex, request=request,
                        current_state=State.RECEIVED,
                        expansion_limit=self.max_context_expansions,
                        prompt_name="03_failure_repair_path" if self.repair_enabled else "02_happy_path_e2e",
                        prompt_version="v1" if self.repair_enabled else "v1.1",
                        repository_identifiers={"canonical": str(canonical),
                                                "target": str(target),
                                                "target_main_commit": git(target, "rev-parse", "main")},
                        started_at=datetime.now(timezone.utc).isoformat())
        self._active_run_id = run.run_id
        self.store.save(run)
        self.store.move(run, State.RECEIVED, "request_created", "Orchestrator")
        self.store.move(run, State.SCOPE_CHECK, "begin_capability_check", "Orchestrator")
        decision = capability(request, target, self.verifier.python)
        if not decision.supported:
            raise ValueError(decision.reasons)
        self.store.move(run, State.ANALYZING_REPO, "supported", "Capability Gate")
        run.analysis = analyze(target)
        self.store.save(run)
        self.store.move(run, State.CONTEXT_BUILDING, "analysis_complete", "Repository Analyzer")
        run.context = select_context(target, run.analysis)
        self.store.save(run)
        self.store.move(run, State.PLANNING, "context_selected", "Context Manager")
        payload = {"request": request.dict(), "analysis": run.analysis.dict(),
                   "context": [item.dict() for item in run.context.items],
                   "context_files": [item.path for item in run.context.items]}
        try:
            run.plan = self.client.call(run.run_id, "Migration Planner", payload, MigrationPlan)
        except RuntimeError:
            self.store.move(run, State.MODEL_ERROR, "invalid_model_output", "Model Client")
            run.final_status = State.MODEL_ERROR.value
            run.ended_at = datetime.now(timezone.utc).isoformat()
            self.store.save(run)
            raise
        self.store.save(run)
        self.store.move(run, State.PATCH_GENERATING, "plan_validated", "Migration Planner")
        try:
            proposal = self.client.call(run.run_id, "Patch Generator", {
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
        self.store.move(run, State.PATCHING_SANDBOX, "proposal_validated", "Patch Generator")
        with Sandbox(target) as sandbox:
            run.patch = apply_proposal(sandbox, proposal)
            bundle = artifact_parent / "sandbox-snapshot.bundle"
            git(sandbox.path, "bundle", "create", str(bundle), "HEAD")
            run.repository_identifiers["sandbox_bundle"] = str(bundle)
            self.store.save(run)
            self.store.move(run, State.VERIFYING_SANDBOX, "sandbox_patch_applied", "Patch Tool")
            run.sandbox_verification = self.verifier.run(sandbox.path)
            self.store.save(run)
            if not run.sandbox_verification.passed:
                if not self.repair_enabled:
                    run.final_status = "sandbox_verification_failed"
                    run.ended_at = datetime.now(timezone.utc).isoformat()
                    self.store.save(run)
                    return run
                if any(check.name == "installed Pydantic v2" and check.exit_code != 0
                       for check in run.sandbox_verification.checks):
                    self.store.move(run, State.ENVIRONMENT_ERROR,
                                    "verification_environment_failed", "Verification Runner")
                    run.final_status = State.ENVIRONMENT_ERROR.value
                    run.ended_at = datetime.now(timezone.utc).isoformat()
                    self.store.save(run)
                    return run
                if not self._repair_until_verified(run, sandbox):
                    return run
                git(sandbox.path, "bundle", "create", str(bundle), "--all")
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
            branch = f"patchpilot/pydantic-v2-{run.run_id[:8]}"
            git(target, "switch", "-c", branch)
            patch_file = artifact_parent / "verified.patch"
            patch_file.write_text(run.patch.diff)
            git(target, "apply", "--check", str(patch_file))
            git(target, "apply", str(patch_file))
            applied = subprocess.run(["git", "diff"], cwd=target, text=True,
                                     capture_output=True, check=True).stdout
            if applied != run.patch.diff:
                raise RuntimeError("target diff differs from sandbox verified diff")
            git(target, "add", "-A")
            git(target, "commit", "-qm", "Apply verified Pydantic v2 patch")
            run.target_branch = branch
            run.repository_identifiers["target_commit"] = git(target, "rev-parse", "HEAD")
            self.store.save(run)
            self.store.move(run, State.VERIFYING_TARGET_BRANCH, "exact_patch_applied", "Patch Tool")
            run.target_verification = self.verifier.run(target)
            self.store.save(run)
            if not run.target_verification.passed:
                run.final_status = "target_verification_failed"
            else:
                self.store.move(run, State.READY_FOR_PR, "checks_passed", "Verification Runner")
                run.final_status = State.READY_FOR_PR.value
            run.ended_at = datetime.now(timezone.utc).isoformat()
            self.store.save(run)
        return run
