"""Approval and patch boundaries."""

from pathlib import Path

import pytest

from patchpilot.sandbox import Sandbox
from patchpilot.workflow.runner import apply_proposal
from patchpilot.workflow.schema import FileChange, PatchProposal

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures/pydantic_v1_app"


def test_patch_rejects_traversal_and_preserves_fixture() -> None:
    original = (FIXTURE / "src/shop/users.py").read_text()
    with Sandbox(FIXTURE) as sandbox:
        proposal = PatchProposal(changes=[FileChange(path="src/../../outside.py",
                                                     content="unsafe")], rationale="test")
        with pytest.raises(ValueError):
            apply_proposal(sandbox, proposal)
        assert sandbox.changed_files() == ()
    assert (FIXTURE / "src/shop/users.py").read_text() == original
