"""Persist one complete Prompt 2 run with deterministic model responses."""

import hashlib
import json
import runpy
import subprocess
import uuid
from pathlib import Path

from patchpilot.workflow import RunStore, VerificationRunner, Workflow
from patchpilot.workflow.model import ModelClient
from patchpilot.workflow.schema import State
from patchpilot.workflow.state import HAPPY_PATH


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    fixture = root / "fixtures/pydantic_v1_app"
    verifier_python = Path("/tmp/patchpilot-pydantic2-venv/bin/python")
    if not verifier_python.is_file():
        raise RuntimeError(f"required Pydantic v2 verifier missing: {verifier_python}")
    before = {str(path.relative_to(fixture)): hashlib.sha256(path.read_bytes()).hexdigest()
              for path in fixture.rglob("*") if path.is_file()}
    artifacts = root / "artifacts" / f"controlled-{uuid.uuid4().hex[:12]}"
    backend = runpy.run_path(str(root / "tests/test_happy_path.py"))["ScriptedSol"]()
    store = RunStore(artifacts / "runs.db")
    run = Workflow(store, ModelClient(backend, store), VerificationRunner(verifier_python)).run(
        fixture, artifacts, approval="APPROVE")
    history = store.history(run.run_id)
    assert run.current_state == State.READY_FOR_PR
    assert [event.next_state for event in history] == list(HAPPY_PATH)
    assert run.sandbox_verification and run.sandbox_verification.passed
    assert run.target_verification and run.target_verification.passed
    assert run.approval and run.approval.decision == "APPROVE"
    assert run.patch and run.proposal and run.plan
    assert len(store.model_calls(run.run_id)) == 2
    target = Path(run.repository_identifiers["target"])
    main_commit = subprocess.check_output(["git", "rev-parse", "main"], cwd=target, text=True).strip()
    assert main_commit == run.repository_identifiers["target_main_commit"]
    evidence = artifacts / "runs" / run.run_id
    assert (evidence / "verified.patch").read_text() == run.patch.diff
    assert (evidence / "target_branch.diff").read_text() == run.patch.diff
    assert hashlib.sha256((evidence / "verified.patch").read_bytes()).hexdigest() == run.patch.sha256
    after = {str(path.relative_to(fixture)): hashlib.sha256(path.read_bytes()).hexdigest()
             for path in fixture.rglob("*") if path.is_file()}
    assert before == after
    print(json.dumps({"run_id": run.run_id, "state": run.current_state.value,
                      "artifacts": str(evidence), "verified_patch_sha256": run.patch.sha256,
                      "target_branch": run.target_branch}, indent=2))


if __name__ == "__main__":
    main()
