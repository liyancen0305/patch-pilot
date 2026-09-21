"""End-to-end migration through a scripted model boundary."""

import hashlib
import json
import os
import subprocess
from pathlib import Path

from patchpilot.workflow import RunStore, VerificationRunner, Workflow
from patchpilot.workflow.model import ModelClient
from patchpilot.workflow.schema import State, VerificationResult
from patchpilot.workflow.state import HAPPY_PATH

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures/pydantic_v1_app"
V2_PYTHON = Path(os.environ.get("PATCHPILOT_V2_PYTHON", "/tmp/patchpilot-pydantic2-venv/bin/python"))


class ScriptedSol:
    model = "gpt-5.6-sol-test-double"

    def complete(self, component: str, payload: dict[str, object], schema: type[object]) -> tuple[dict[str, object], int, int]:
        if component == "Migration Planner":
            paths = ["pyproject.toml", "src/shop/base.py", "src/shop/users.py",
                     "src/shop/orders.py", "tests/test_shop.py"]
            return {"summary": "Pydantic v2 migration",
                    "planned_changes": [{"file": path, "symbol": "Pydantic models",
                                         "reason": "v1 dependency or API",
                                         "change": "Use v2 API",
                                         "expected_effect": "Preserve behavior"}
                                        for path in paths],
                    "affected_files": paths, "risks": ["validator semantics"],
                    "validation_plan": ["pytest", "mypy", "ruff", "runtime"]}, 100, 80
        files = {
            "pyproject.toml": (FIXTURE / "pyproject.toml").read_text().replace(
                "pydantic==1.10.26", "pydantic>=2,<3"),
            "src/shop/base.py": '''"""Shared Pydantic v2 model configuration."""

from pydantic import BaseModel, ConfigDict


class ShopModel(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid", validate_assignment=True)
''',
            "src/shop/users.py": '''"""User model and field validation."""

from pydantic import field_validator

from .base import ShopModel


class User(ShopModel):
    id: int
    email: str
    name: str

    @field_validator("id")
    @classmethod
    def positive_id(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("id must be positive")
        return value

    @field_validator("email")
    @classmethod
    def normalized_email(cls, value: str) -> str:
        value = value.lower()
        if "@" not in value or value.startswith("@") or value.endswith("@"):
            raise ValueError("invalid email")
        return value
''',
            "src/shop/orders.py": '''"""Order models with cross-field validation."""

from pydantic import field_validator, model_validator
from typing_extensions import Self

from .base import ShopModel
from .users import User


class OrderItem(ShopModel):
    sku: str
    quantity: int
    unit_price_cents: int

    @field_validator("quantity", "unit_price_cents")
    @classmethod
    def positive_amount(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("amount must be positive")
        return value


class Order(ShopModel):
    id: int
    customer: User
    items: list[OrderItem]
    total_cents: int

    @model_validator(mode="after")
    def total_matches_items(self) -> Self:
        expected = sum(item.quantity * item.unit_price_cents for item in self.items)
        if self.total_cents != expected:
            raise ValueError("total does not match items")
        return self
''',
            "tests/test_shop.py": (FIXTURE / "tests/test_shop.py").read_text()
            .replace(".parse_obj(", ".model_validate(")
            .replace(".dict()", ".model_dump()"),
        }
        return {"changes": [{"path": path, "content": content}
                            for path, content in files.items()],
                "rationale": "Replace Pydantic v1 APIs"}, 300, 500


def test_complete_happy_path(tmp_path: Path) -> None:
    assert V2_PYTHON.is_file(), f"required Pydantic v2 verification Python missing: {V2_PYTHON}"
    before = {path.relative_to(FIXTURE): path.read_bytes()
              for path in FIXTURE.rglob("*") if path.is_file() and ".git" not in path.parts}
    store = RunStore(tmp_path / "runs.db")
    class TrackingVerifier(VerificationRunner):
        calls = 0
        target_clean_before_approval = False

        def run(self, root: Path) -> VerificationResult:
            self.calls += 1
            if self.calls == 1:
                target = tmp_path / "artifacts/target"
                status = subprocess.check_output(["git", "-C", str(target), "status", "--porcelain"],
                                                 text=True).strip()
                self.target_clean_before_approval = not status and root != target
            return super().run(root)

    verifier = TrackingVerifier(V2_PYTHON)
    workflow = Workflow(store, ModelClient(ScriptedSol(), store), verifier)
    run = workflow.run(FIXTURE, tmp_path / "artifacts", approval="APPROVE")
    assert verifier.calls == 2
    assert verifier.target_clean_before_approval
    assert run.current_state == State.READY_FOR_PR
    assert store.load(run.run_id).current_state == State.READY_FOR_PR
    assert [event.next_state for event in store.history(run.run_id)] == list(HAPPY_PATH)
    assert len(store.model_calls(run.run_id)) == 2
    assert run.sandbox_verification and run.sandbox_verification.passed
    assert run.target_verification and run.target_verification.passed
    assert run.approval and run.approval.decision == "APPROVE"
    assert run.patch is not None
    target = tmp_path / "artifacts/target"
    main = subprocess.check_output(["git", "-C", str(target), "rev-parse", "main"],
                                   text=True).strip()
    assert main == run.repository_identifiers["target_main_commit"]
    assert subprocess.check_output(["git", "-C", str(target), "diff", "main", "HEAD"],
                                   text=True) == run.patch.diff
    assert subprocess.check_output(["git", "-C", str(target), "show",
                                    "main:pyproject.toml"]) == (FIXTURE / "pyproject.toml").read_bytes()
    assert all((FIXTURE / path).read_bytes() == content for path, content in before.items())

    evidence = tmp_path / "artifacts" / "runs" / run.run_id
    assert (evidence / "run.sqlite3").exists()
    assert (evidence / "verified.patch").read_text() == run.patch.diff
    assert hashlib.sha256((evidence / "verified.patch").read_bytes()).hexdigest() == run.patch.sha256
    assert (evidence / "target_branch.diff").read_text() == run.patch.diff
    assert json.loads((evidence / "summary.json").read_text())["final_state"] == "READY_FOR_PR"
    assert len(json.loads((evidence / "state_history.json").read_text())) == len(HAPPY_PATH)
    assert json.loads((evidence / "migration_plan.json").read_text())["summary"]
    assert json.loads((evidence / "patch_proposal.json").read_text())["changes"]
