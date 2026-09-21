"""Prompt 2 happy path orchestrator."""

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
from .repository import analyze, capability, select_context
from .schema import (
    ApprovalDecision,
    MigrationPlan,
    MigrationRequest,
    PatchProposal,
    PatchResult,
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
                 verifier: VerificationRunner) -> None:
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

    def _run(self, canonical: Path, artifact_parent: Path,
             approval: str) -> RunRecord:
        canonical = canonical.resolve(strict=True)
        artifact_parent.mkdir(parents=True, exist_ok=True)
        target = create_target(canonical, artifact_parent)
        request = MigrationRequest(repository=str(target))
        run = RunRecord(run_id=uuid.uuid4().hex, request=request,
                        current_state=State.RECEIVED,
                        prompt_name="02_happy_path_e2e",
                        prompt_version="v1.1",
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
                run.final_status = "sandbox_verification_failed"
                run.ended_at = datetime.now(timezone.utc).isoformat()
                self.store.save(run)
                return run
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
