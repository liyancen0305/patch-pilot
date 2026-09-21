"""Targeted Prompt 2 invariants."""

import sqlite3
import sys
import venv
from pathlib import Path

import pytest
from test_happy_path import ScriptedSol

from patchpilot.sandbox import Sandbox
from patchpilot.tools.repository import search_text as actual_search
from patchpilot.workflow import RunStore, repository
from patchpilot.workflow.guardrails import validate_test_change
from patchpilot.workflow.repository import analyze, capability, select_context
from patchpilot.workflow.runner import VerificationRunner, apply_proposal, create_target
from patchpilot.workflow.schema import (
    FileChange,
    MigrationRequest,
    PatchProposal,
    RunRecord,
    State,
)

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures/pydantic_v1_app"
EXTERNAL_PYTHON = Path("/tmp/patchpilot-pydantic2-venv/bin/python")


def _proposal(sandbox: Sandbox) -> PatchProposal:
    original = sandbox.current_file("src/shop/users.py")
    return PatchProposal(changes=[FileChange(path="src/shop/users.py",
                                             content=original + "\n# candidate\n")],
                         rationale="test candidate")


def test_candidate_does_not_advance_stable_until_promoted() -> None:
    with Sandbox(FIXTURE) as sandbox:
        baseline = sandbox.last_stable_snapshot
        patch = apply_proposal(sandbox, _proposal(sandbox))
        assert patch.pre_snapshot == baseline
        assert patch.post_snapshot != baseline
        assert sandbox.last_stable_snapshot == baseline
        sandbox.promote_candidate(patch.post_snapshot)
        assert sandbox.last_stable_snapshot == patch.post_snapshot


def test_failed_candidate_keeps_previous_stable_and_rollback_restores_it() -> None:
    with Sandbox(FIXTURE) as sandbox:
        baseline = sandbox.last_stable_snapshot
        original = sandbox.current_file("src/shop/users.py")
        apply_proposal(sandbox, _proposal(sandbox))
        verification = VerificationRunner(Path(sys.executable)).run(sandbox.path)
        assert not verification.passed
        assert sandbox.last_stable_snapshot == baseline
        sandbox.rollback()
        assert sandbox.last_stable_snapshot == baseline
        assert sandbox.current_file("src/shop/users.py") == original
        assert sandbox.changed_files() == ()


@pytest.mark.skipif(not EXTERNAL_PYTHON.exists(), reason="external v2 runtime absent")
def test_successful_verification_promotes_candidate() -> None:
    data, _input_tokens, _output_tokens = ScriptedSol().complete(
        "Patch Generator", {}, PatchProposal)
    proposal = PatchProposal.parse_obj(data)
    with Sandbox(FIXTURE) as sandbox:
        baseline = sandbox.last_stable_snapshot
        patch = apply_proposal(sandbox, proposal)
        assert sandbox.last_stable_snapshot == baseline
        verification = VerificationRunner(EXTERNAL_PYTHON).run(sandbox.path)
        assert verification.passed
        sandbox.promote_candidate(patch.post_snapshot)
        assert sandbox.last_stable_snapshot == patch.post_snapshot


@pytest.mark.skipif(not EXTERNAL_PYTHON.exists(), reason="external v2 runtime absent")
def test_capability_uses_external_verification_python(tmp_path: Path) -> None:
    target = create_target(FIXTURE, tmp_path)
    request = MigrationRequest(repository=str(target))
    assert EXTERNAL_PYTHON != Path(sys.executable)
    decision = capability(request, target, EXTERNAL_PYTHON)
    assert decision.supported, decision.reasons


def test_capability_rejects_missing_tools_in_configured_environment(tmp_path: Path) -> None:
    target = create_target(FIXTURE, tmp_path)
    bare = tmp_path / "bare-python"
    venv.EnvBuilder(with_pip=False).create(bare)
    decision = capability(MigrationRequest(repository=str(target)), target,
                          bare / "bin/python")
    assert not decision.supported
    assert any("pytest unavailable" in reason for reason in decision.reasons)
    assert any("mypy unavailable" in reason for reason in decision.reasons)
    assert any("ruff unavailable" in reason for reason in decision.reasons)


def test_analyzer_records_rg_ast_toml_and_test_reference_evidence(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    def recording_search(root: Path, pattern: str) -> tuple[str, ...]:
        calls.append(pattern)
        return actual_search(root, pattern)

    monkeypatch.setattr(repository, "search_text", recording_search)
    result = analyze(FIXTURE)
    assert len(calls) > 1
    assert result.pydantic_version == "==1.10.26"
    assert any("TOML dependency" in item for item in result.evidence["pyproject.toml"])
    assert any(item.startswith("rg:") for item in result.evidence["src/shop/orders.py"])
    assert any(item.startswith("AST class") for item in result.evidence["src/shop/orders.py"])
    assert any("rg reference to Order" in item for item in result.evidence["tests/test_shop.py"])


def test_context_snippet_ranking_and_independent_budgets(tmp_path: Path) -> None:
    analysis = analyze(FIXTURE)
    ranked = select_context(FIXTURE, analysis, max_files=5, max_snippets=12,
                            max_context_tokens=5000)
    assert len(ranked.items) > len({item.path for item in ranked.items})
    assert ranked.items[0].score >= ranked.items[-1].score
    assert all(item.symbol and item.location and item.reason for item in ranked.items)
    assert any("direct migrated API" in item.reason for item in ranked.items)
    two_snippets = select_context(FIXTURE, analysis, max_files=5, max_snippets=2,
                                  max_context_tokens=5000)
    assert len(two_snippets.items) == 2
    one_file = select_context(FIXTURE, analysis, max_files=1, max_snippets=8,
                              max_context_tokens=5000)
    assert len({item.path for item in one_file.items}) == 1
    tiny_budget = ranked.items[0].token_estimate
    budgeted = select_context(FIXTURE, analysis, max_files=5, max_snippets=12,
                              max_context_tokens=tiny_budget)
    assert budgeted.total_token_estimate <= tiny_budget
    assert len(budgeted.items) < len(ranked.items)
    store = RunStore(tmp_path / "runs.db")
    run = RunRecord(run_id="context-test", request=MigrationRequest(repository=str(FIXTURE)),
                    current_state=State.RECEIVED, repository_identifiers={},
                    context=ranked, started_at="2026-01-01T00:00:00Z")
    store.save(run)
    reloaded = store.load(run.run_id)
    assert reloaded.context and reloaded.context.items[0].reason == ranked.items[0].reason
    with sqlite3.connect(store.path) as db:
        assert db.execute("SELECT count(*) FROM runs").fetchone() == (1,)


def test_regression_assertion_change_is_rejected() -> None:
    original = (FIXTURE / "tests/test_shop.py").read_text()
    migrated = original.replace(".parse_obj(", ".model_validate(").replace(
        ".dict()", ".model_dump()")
    validate_test_change(original, migrated)
    weakened = migrated.replace('assert user.name == "Ada"', 'assert user.name == "Eve"')
    with pytest.raises(ValueError, match="expectations changed"):
        validate_test_change(original, weakened)
    with Sandbox(FIXTURE) as sandbox:
        proposal = PatchProposal(changes=[FileChange(path="tests/test_shop.py",
                                                     content=weakened)], rationale="weaken test")
        with pytest.raises(ValueError, match="expectations changed"):
            apply_proposal(sandbox, proposal)
        assert sandbox.changed_files() == ()
