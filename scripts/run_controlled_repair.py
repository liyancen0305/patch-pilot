"""Persist one real-verifier Prompt 3 repair run with controlled model outputs."""

import hashlib
import json
import runpy
import subprocess
import sys
import uuid
from pathlib import Path

from patchpilot.workflow import RunStore, VerificationRunner, Workflow
from patchpilot.workflow.model import ModelClient
from patchpilot.workflow.schema import State


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    fixture = root / "fixtures/pydantic_v1_app"
    verifier_python = Path("/tmp/patchpilot-pydantic2-venv/bin/python")
    if not verifier_python.is_file():
        raise RuntimeError(f"required Pydantic v2 verifier missing: {verifier_python}")
    before = {str(path.relative_to(fixture)): hashlib.sha256(path.read_bytes()).hexdigest()
              for path in fixture.rglob("*") if path.is_file()}
    artifacts = root / "artifacts" / f"controlled-repair-{uuid.uuid4().hex[:12]}"
    sys.path.insert(0, str(root / "tests"))
    backend = runpy.run_path(str(root / "tests/test_prompt3_repair.py"))["RepairModel"]()
    store = RunStore(artifacts / "runs.db")
    run = Workflow(store, ModelClient(backend, store), VerificationRunner(verifier_python),
                   repair_enabled=True).run(fixture, artifacts, approval="APPROVE")
    assert run.current_state == State.READY_FOR_PR and run.attempt_number == 2
    assert run.patch and run.sandbox_verification and run.sandbox_verification.passed
    assert run.target_verification and run.target_verification.passed
    assert run.approval and run.approval.decision == "APPROVE"
    target = Path(run.repository_identifiers["target"])
    main_commit = subprocess.check_output(["git", "rev-parse", "main"], cwd=target,
                                          text=True).strip()
    assert main_commit == run.repository_identifiers["target_main_commit"]
    evidence = artifacts / "runs" / run.run_id
    assert (evidence / "verified.patch").read_text() == run.patch.diff
    assert (evidence / "target_branch.diff").read_text() == run.patch.diff
    assert hashlib.sha256((evidence / "verified.patch").read_bytes()).hexdigest() == run.patch.sha256
    after = {str(path.relative_to(fixture)): hashlib.sha256(path.read_bytes()).hexdigest()
             for path in fixture.rglob("*") if path.is_file()}
    assert before == after
    print(json.dumps({"run_id": run.run_id, "attempt_number": run.attempt_number,
                      "state": run.current_state.value, "artifacts": str(evidence),
                      "verified_patch_sha256": run.patch.sha256,
                      "target_branch": run.target_branch}, indent=2))


if __name__ == "__main__":
    main()
