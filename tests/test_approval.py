"""Approval cannot be bypassed by a verified sandbox patch."""

import os
import subprocess
from pathlib import Path

import pytest
from test_happy_path import FIXTURE, ScriptedSol

from patchpilot.workflow import RunStore, VerificationRunner, Workflow
from patchpilot.workflow.model import ModelClient
from patchpilot.workflow.schema import State

V2_PYTHON = Path(os.environ.get("PATCHPILOT_V2_PYTHON", "/tmp/patchpilot-pydantic2-venv/bin/python"))


@pytest.mark.skipif(not V2_PYTHON.exists(), reason="Pydantic v2 verification environment absent")
def test_declined_approval_preserves_target_main(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "runs.db")
    run = Workflow(store, ModelClient(ScriptedSol(), store),
                   VerificationRunner(V2_PYTHON)).run(FIXTURE, tmp_path / "artifacts",
                                                        approval="DECLINE")
    target = tmp_path / "artifacts/target"
    assert run.current_state == State.AWAITING_APPROVAL
    assert run.approval and run.approval.decision == "DECLINE"
    assert run.target_branch is None
    assert subprocess.check_output(["git", "-C", str(target), "branch", "--show-current"],
                                   text=True).strip() == "main"
    assert subprocess.check_output(["git", "-C", str(target), "status", "--porcelain"],
                                   text=True) == ""
