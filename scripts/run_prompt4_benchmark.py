"""Run the fixed five-family benchmark through the existing workflow."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from patchpilot.workflow import RunStore, VerificationRunner, Workflow
from patchpilot.workflow.benchmarks import FAMILIES, MigrationFamily
from patchpilot.workflow.model import ModelClient
from patchpilot.workflow.schema import RunRecord, State

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = {
    "pydantic": ROOT / "fixtures/pydantic_v1_app",
    "sqlalchemy": ROOT / "fixtures/sqlalchemy_14",
    "httpx": ROOT / "fixtures/httpx_027",
    "openai": ROOT / "fixtures/openai_028",
    "celery": ROOT / "fixtures/celery_4",
}
SOLUTION = {
    "sqlalchemy": ROOT / "benchmark_solutions/sqlalchemy_14",
    "httpx": ROOT / "benchmark_solutions/httpx_027",
    "openai": ROOT / "benchmark_solutions/openai_028",
    "celery": ROOT / "benchmark_solutions/celery_4",
}
TARGET_ENV = {
    "pydantic": Path("/tmp/patchpilot-pydantic2-venv/bin/python"),
    "sqlalchemy": Path("/tmp/patchpilot-p4-sqlalchemy-new/bin/python"),
    "httpx": Path("/tmp/patchpilot-p4-httpx-new/bin/python"),
    "openai": Path("/tmp/patchpilot-p4-openai-new/bin/python"),
    "celery": Path("/tmp/patchpilot-p4-celery-new/bin/python"),
}
FAILURE_FILE = {
    "sqlalchemy": "src/ledger/repository.py",
    "httpx": "src/remote/service.py",
    "openai": "src/assistant_app/gateway.py",
    "celery": "src/jobs/config.py",
}


def file_hashes(root: Path) -> dict[str, str]:
    return {
        str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in root.rglob("*") if path.is_file()
        and not any(part.startswith(".") or part == "__pycache__"
                    for part in path.relative_to(root).parts)
    }


def candidate_content(case: str, good: str, stage: int) -> str:
    """Controlled wrong behavior in the fixture's actual migration surface."""
    if case == "sqlalchemy":
        return good.replace("Account.owner == owner",
                            'Account.owner == "Missing"' if stage == 0 else
                            'Account.owner == "Bo"')
    if case == "httpx":
        if stage == 0:
            return good.replace("        response.raise_for_status()\n", "")
        return good.replace("        response.raise_for_status()\n",
                            "        if response.status_code >= 500:\n"
                            "            response.raise_for_status()\n")
    if case == "openai":
        return good.replace("return str(response.choices[0].message.content)",
                            "return str(response.choices[0].message.content).upper()"
                            if stage == 0 else
                            "return str(response.choices[0].message.content).title()")
    if case == "celery":
        return good.replace("task_eager_propagates = True",
                            "task_eager_propagates = False" if stage == 0 else
                            "task_eager_propagates = 0" if stage == 1 else
                            "task_eager_propagates = bool(0)")
    raise ValueError(case)


class ControlledBenchmarkModel:
    """Only the model boundary is scripted; every workflow tool runs normally."""

    model = "controlled-benchmark-test-double"

    def __init__(self, family: MigrationFamily, *, repair_pass_on: int = 0,
                 reviewer: bool = False, more_evidence: bool = False) -> None:
        self.family = family
        self.repair_pass_on = repair_pass_on
        self.reviewer = reviewer
        self.more_evidence = more_evidence
        self.repairs = 0
        self.reviews = 0
        self.components: list[str] = []

    def _contents(self) -> dict[str, str]:
        fixture = FIXTURES[self.family.name]
        solution = SOLUTION[self.family.name]
        changes = {
            str(path.relative_to(solution)): path.read_text()
            for path in solution.rglob("*") if path.is_file()
            and (path.suffix == ".py" or path.name == "pyproject.toml")
        }
        if self.repair_pass_on:
            failure_file = FAILURE_FILE[self.family.name]
            good = changes.get(failure_file, (fixture / failure_file).read_text())
            changes[failure_file] = candidate_content(self.family.name, good, 0)
        return changes

    def complete(self, component: str, payload: dict[str, Any],
                 schema: type[Any]) -> tuple[dict[str, Any], int, int]:
        self.components.append(component)
        if component == "Migration Planner":
            paths = list(self._contents())
            return {
                "summary": f"{self.family.name} supported-version migration",
                "planned_changes": [
                    {"file": path, "symbol": "dependency or affected application behavior",
                     "reason": "old API or dependency compatibility",
                     "change": "migrate to supported API while preserving behavior",
                     "expected_effect": "existing regression behavior remains"}
                    for path in paths],
                "affected_files": paths,
                "risks": ["behavioral regression at migration boundary"],
                "validation_plan": ["migration-specific", "pytest", "mypy",
                                    "ruff", "runtime/import"],
            }, 0, 0
        if component == "Patch Generator":
            return {
                "changes": [{"path": path, "content": content}
                            for path, content in self._contents().items()],
                "rationale": f"controlled {self.family.name} migration proposal",
            }, 0, 0
        if component == "Failure Analyzer":
            failure_file = FAILURE_FILE[self.family.name]
            requested: list[str] = []  # Reviewer may request additional focused evidence.
            return {
                "failure_type": "migration_behavior_regression",
                "likely_root_cause": "migration candidate changed tested behavior",
                "supporting_evidence": ["real pytest regression output"],
                "proposed_repair": "restore the tested behavior in the affected file",
                "files_to_modify": [failure_file],
                "reason_for_each_file": [{
                    "file": failure_file,
                    "reason": "the regression exercises this migration boundary",
                    "supporting_evidence": "failing regression test and current diff",
                    "expected_effect": "restore the original business behavior",
                    "required_verification": "complete verification suite",
                }],
                "additional_context_needed": requested,
                "confidence": 0.5 if self.reviewer else 0.95,
            }, 0, 0
        if component == "Change Reviewer":
            self.reviews += 1
            need_more = self.more_evidence and self.reviews == 1
            return {
                "decision": "NEED_MORE_EVIDENCE" if need_more else "APPROVE",
                "reason": "independent review of migration regression evidence",
                "supporting_evidence": ["failing test and affected code"],
                "risk": "moderate",
                "additional_context_needed":
                    ["tests/test_assistant_app.py"] if need_more else [],
                "required_verification": ["complete verification suite"],
            }, 0, 0
        if component == "Repair Generator":
            self.repairs += 1
            failure_file = FAILURE_FILE[self.family.name]
            good = (SOLUTION[self.family.name] / failure_file)
            good_content = (good.read_text() if good.is_file() else
                            (FIXTURES[self.family.name] / failure_file).read_text())
            content = (good_content if self.repairs >= self.repair_pass_on else
                       candidate_content(self.family.name, good_content, self.repairs))
            return {"changes": [{"path": failure_file, "content": content}],
                    "rationale": "approved repair of tested behavior"}, 0, 0
        raise AssertionError(component)


def run_case(family: MigrationFamily, scenario: str, artifacts: Path) -> RunRecord:
    artifacts = artifacts.resolve()
    fixture = FIXTURES[family.name]
    before = file_hashes(fixture)
    if family.name == "pydantic":
        sys.path.insert(0, str(ROOT / "tests"))
        if scenario == "happy":
            from test_happy_path import ScriptedSol
            backend: Any = ScriptedSol()
        elif scenario == "repair2":
            from test_prompt3_repair import RepairModel
            backend = RepairModel()
        else:
            raise ValueError(scenario)
    else:
        options: dict[str, Any] = {}
        if scenario == "repair2":
            options["repair_pass_on"] = 1
        elif scenario == "repair3":
            options["repair_pass_on"] = 2
        elif scenario == "max3":
            options["repair_pass_on"] = 3
        elif scenario == "reviewer_context":
            options.update(repair_pass_on=1, reviewer=True, more_evidence=True)
        elif scenario != "happy":
            raise ValueError(scenario)
        if family.name == "celery" and scenario == "max3":
            options["reviewer"] = True
        backend = ControlledBenchmarkModel(family, **options)
    verification_python = TARGET_ENV[family.name]
    if not verification_python.is_file():
        raise RuntimeError(f"real verification environment missing: {verification_python}")
    destination = artifacts / family.name / scenario
    store = RunStore(destination / "runs.db")
    run = Workflow(store, ModelClient(backend, store),
                   VerificationRunner(verification_python),
                   repair_enabled=scenario != "happy",
                   benchmark_mode=True).run(fixture, destination, approval="APPROVE")
    assert file_hashes(fixture) == before
    target = Path(run.repository_identifiers["target"])
    main = subprocess.check_output(["git", "rev-parse", "main"], cwd=target,
                                   text=True).strip()
    assert main == run.repository_identifiers["target_main_commit"]
    if run.current_state == State.READY_FOR_PR:
        assert run.patch and run.sandbox_verification and run.sandbox_verification.passed
        assert run.target_verification and run.target_verification.passed
        assert run.approval and run.approval.decision == "APPROVE"
        assert subprocess.check_output(["git", "diff", "main", "HEAD"], cwd=target,
                                       text=True) == run.patch.diff
    return run


def main() -> None:
    artifacts = ROOT / "artifacts/benchmark"
    scenarios = {
        "pydantic": ["happy", "repair2"],
        "sqlalchemy": ["happy", "repair2"],
        "httpx": ["happy", "repair3"],
        "openai": ["happy", "reviewer_context"],
        "celery": ["happy", "max3"],
    }
    results = []
    for family in FAMILIES:
        for scenario in scenarios[family.name]:
            run = run_case(family, scenario, artifacts / "runs")
            results.append({
                "use_case": family.use_case, "migration": family.goal,
                "migration_family": family.name, "dependency_name": family.dependency_name,
                "source_version": family.source_version, "target_version": family.target_version,
                "prompt_name": run.prompt_name, "prompt_version": run.prompt_version,
                "scenario": scenario,
                "run_id": run.run_id, "final_state": run.current_state.value,
                "attempt_count": run.attempt_number,
                "reviewer_invoked": bool(run.review_history),
                "context_expansions": len(run.context_expansions),
                "sandbox_verification": run.sandbox_verification.passed
                    if run.sandbox_verification else None,
                "target_verification": run.target_verification.passed
                    if run.target_verification else None,
                "verification_status": ("passed" if run.target_verification and
                                        run.target_verification.passed else
                                        "failed" if run.sandbox_verification else "not_run"),
                "known_limitation": "controlled model responses; live Sol quality deferred",
            })
            print(f"{family.name} {scenario}: {run.current_state.value}", flush=True)
    write_summary(results, artifacts)


def write_summary(results: list[dict[str, Any]], artifacts: Path) -> None:
    families = []
    for family in FAMILIES:
        rows = [row for row in results if row["migration_family"] == family.name]
        happy = next(row for row in rows if row["scenario"] == "happy")
        repair = next((row for row in rows if row["scenario"] != "happy"), None)
        families.append({
            "use_case": family.use_case, "migration": family.goal,
            "migration_family": family.name,
            "dependency_name": family.dependency_name,
            "source_version": family.source_version,
            "target_version": family.target_version,
            "happy_path_final_state": happy["final_state"],
            "happy_path_attempts": happy["attempt_count"],
            "repair_path_exercised": repair["scenario"] if repair else None,
            "repair_attempts": repair["attempt_count"] if repair else None,
            "repair_final_state": repair["final_state"] if repair else None,
            "reviewer_invoked": repair["reviewer_invoked"] if repair else False,
            "context_expansions": repair["context_expansions"] if repair else 0,
            "verification_status": "passed" if happy["target_verification"] else "failed",
            "known_limitation": (
                "Celery 4 baseline requires Python 3.10; controlled test double; "
                "live model quality deferred" if family.name == "celery" else
                "controlled test double; live model quality deferred"),
        })
    artifacts.mkdir(parents=True, exist_ok=True)
    (artifacts / "prompt4_summary.json").write_text(
        json.dumps({"benchmark_set": [item.name for item in FAMILIES],
                    "prompt_name": "04_remaining_use_cases", "prompt_version": "v1.1",
                    "families": families, "runs": results}, indent=2) + "\n")


if __name__ == "__main__":
    main()
