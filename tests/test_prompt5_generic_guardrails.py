"""Configuration-driven regression-test and file-scope guardrails."""

import shutil
from pathlib import Path

import pytest

from patchpilot.workflow import RunStore
from patchpilot.workflow.benchmarks import FAMILIES
from patchpilot.workflow.capability import proposal_violation
from patchpilot.workflow.guardrails import (
    build_allowed_scope,
    file_scope_reason,
    validate_test_change,
)
from patchpilot.workflow.repository import analyze
from patchpilot.workflow.schema import (
    FileChange,
    MigrationRequest,
    PatchProposal,
    RunRecord,
    State,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = {
    "pydantic": "pydantic_v1_app", "sqlalchemy": "sqlalchemy_14",
    "httpx": "httpx_027", "openai": "openai_028", "celery": "celery_4",
}


def test_configured_test_rewrites_preserve_behavior() -> None:
    pydantic = FAMILIES[0]
    httpx = FAMILIES[2]
    old = 'def test_model():\n    assert User.parse_obj({"x": 1}).dict() == {"x": 1}\n'
    new = old.replace("parse_obj", "model_validate").replace(".dict()", ".model_dump()")
    used = validate_test_change(old, new, pydantic.allowed_test_api_rewrites)
    assert {rule.new_api for rule in used} == {"model_validate", "model_dump"}
    old_httpx = 'def test_client():\n    assert make_client(proxies="proxy") is not None\n'
    new_httpx = old_httpx.replace("proxies=", "proxy=")
    assert validate_test_change(old_httpx, new_httpx, httpx.allowed_test_api_rewrites)
    with pytest.raises(ValueError, match="expectations changed"):
        validate_test_change(old_httpx, new_httpx, FAMILIES[1].allowed_test_api_rewrites)
    with pytest.raises(ValueError, match="expectations changed"):
        validate_test_change(old, new.replace('== {"x": 1}', '== {"x": 2}'),
                             pydantic.allowed_test_api_rewrites)
    with pytest.raises(ValueError, match="expectations changed"):
        validate_test_change(old, new.replace(' == {"x": 1}', ''),
                             pydantic.allowed_test_api_rewrites)
    source = (ROOT / "src/patchpilot/workflow/guardrails.py").read_text()
    assert all(api not in source for api in ("model_validate", "parse_obj", "model_dump"))


@pytest.mark.parametrize("family", FAMILIES, ids=lambda item: item.name)
def test_scope_uses_family_and_discovered_repository_files(tmp_path: Path, family: object) -> None:
    name = family.name  # type: ignore[attr-defined]
    root = tmp_path / "fixture"
    shutil.copytree(ROOT / "fixtures" / FIXTURES[name], root,
                    ignore=shutil.ignore_patterns(".git", "__pycache__"))
    (root / "requirements.txt").write_text(f"{family.dependency_name}=={family.source_version}\n")  # type: ignore[attr-defined]
    (root / "setup.cfg").write_text("[tool:pytest]\naddopts = -q\n")
    (root / "unrelated.txt").write_text("unrelated\n")
    (root / ".env").write_text("SECRET=value\n")
    if name == "sqlalchemy":
        (root / "alembic.ini").write_text("[alembic]\nscript_location = migrations\n")
    if name == "celery":
        (root / "celeryconfig.py").write_text("broker_url = 'memory://'\n")
    analysis = analyze(root)
    scope = build_allowed_scope(root, analysis, family)  # type: ignore[arg-type]
    assert file_scope_reason(root, scope, "requirements.txt") is None
    assert file_scope_reason(root, scope, "setup.cfg") is None
    if name == "sqlalchemy":
        assert file_scope_reason(root, scope, "alembic.ini") is None
    if name == "celery":
        assert file_scope_reason(root, scope, "celeryconfig.py") is None
    assert file_scope_reason(root, scope, "unrelated.txt") is not None
    assert file_scope_reason(root, scope, ".env") is not None
    assert file_scope_reason(root, scope, "../outside.py") is not None
    assert scope.files["setup.cfg"].category == "configuration"
    assert scope.files["requirements.txt"].reason
    proposal = PatchProposal(changes=[FileChange(path="setup.cfg",
        content="[tool:pytest]\naddopts = -q -x\n")], rationale="migration config")
    decisions = []
    assert proposal_violation(root, proposal, "Patch Generator", scope,
                              family.allowed_test_api_rewrites, decisions) is None  # type: ignore[attr-defined]
    assert decisions and decisions[0].decision == "ALLOWED" and decisions[0].category == "configuration"


def test_guardrail_scope_and_decision_survive_sqlite(tmp_path: Path) -> None:
    family = FAMILIES[1]
    root = ROOT / "fixtures/sqlalchemy_14"
    scope = build_allowed_scope(root, analyze(root), family)
    proposal = PatchProposal(changes=[FileChange(path="pyproject.toml",
        content=(root / "pyproject.toml").read_text())], rationale="dependency")
    decisions = []
    assert proposal_violation(root, proposal, "Patch Generator", scope,
                              family.allowed_test_api_rewrites, decisions) is None
    run = RunRecord(run_id="scope-audit", request=MigrationRequest(
        repository=str(root), migration_goal=family.goal), current_state=State.RECEIVED,
        repository_identifiers={}, use_case=family.use_case,
        migration_family=family.name, started_at="2026-01-01T00:00:00Z",
        allowed_modification_scope=scope, guardrail_decisions=decisions)
    store = RunStore(tmp_path / "runs.db")
    store.save(run)
    saved = store.load(run.run_id)
    assert saved.allowed_modification_scope and saved.allowed_modification_scope.files[
        "pyproject.toml"].category == "dependency"
    assert saved.guardrail_decisions[0].decision == "ALLOWED"
    assert saved.guardrail_decisions[0].reason
