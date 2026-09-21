"""Prompt 2 workflow contracts."""

import itertools
from pathlib import Path

import pytest
from pydantic import ValidationError

from patchpilot.workflow.repository import analyze, select_context
from patchpilot.workflow.schema import MigrationPlan, PatchProposal, State
from patchpilot.workflow.state import HAPPY_PATH, transition

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures/pydantic_v1_app"


def test_state_machine_and_schemas() -> None:
    assert transition(None, State.RECEIVED, "created", "test").previous_state == "INITIAL"
    for previous, following in itertools.pairwise(HAPPY_PATH):
        assert transition(previous, following, "event", "test").next_state == following
    with pytest.raises(ValueError):
        transition(State.RECEIVED, State.READY_FOR_PR, "skip", "test")
    with pytest.raises(ValidationError):
        MigrationPlan.parse_obj({"summary": "malformed"})
    with pytest.raises(ValidationError):
        PatchProposal.parse_obj({"changes": [{"path": "x"}], "rationale": "bad"})


def test_analysis_and_context_budget() -> None:
    analysis = analyze(FIXTURE)
    assert analysis.pydantic_version == "==1.10.26"
    assert "src/shop/orders.py" in analysis.source_files
    assert "root_validator" in analysis.v1_usages["src/shop/orders.py"]
    assert "tests/test_shop.py" in analysis.related_tests["src/shop/orders.py"]
    context = select_context(FIXTURE, analysis, max_files=2, max_snippets=2,
                             max_context_tokens=5000)
    assert len(context.items) == 2
    assert len(context.items) < len(analysis.source_files) + len(analysis.test_files)
    assert all(item.reason for item in context.items)
