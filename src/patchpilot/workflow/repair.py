"""Prompt 3 failure analysis and deterministic repair policy."""

import re
from pathlib import Path
from typing import Any

from .model import ModelClient
from .schema import (
    FailureAnalysis,
    MigrationPlan,
    PatchProposal,
    RepositoryAnalysis,
    ReviewDecision,
    VerificationResult,
)


def failure_text(verification: VerificationResult) -> str:
    return "\n".join(f"{check.name}: {check.output}" for check in verification.checks
                     if check.exit_code != 0)


def relevant_code(root: Path, paths: list[str]) -> dict[str, str]:
    code: dict[str, str] = {}
    for name in dict.fromkeys(paths):
        path = (root / name).resolve()
        if path.is_file() and path.is_relative_to(root.resolve()):
            code[name] = path.read_text()[:12000]
    return code


class FailureAnalyzer:
    def __init__(self, client: ModelClient) -> None:
        self.client = client

    def analyze(self, run_id: str, payload: dict[str, Any]) -> FailureAnalysis:
        return self.client.call(run_id, "Failure Analyzer", payload, FailureAnalysis)


class ChangeReviewer:
    def __init__(self, client: ModelClient) -> None:
        self.client = client

    def review(self, run_id: str, payload: dict[str, Any]) -> ReviewDecision:
        return self.client.call(run_id, "Change Reviewer", payload, ReviewDecision)


class RepairGenerator:
    def __init__(self, client: ModelClient) -> None:
        self.client = client

    def generate(self, run_id: str, payload: dict[str, Any]) -> PatchProposal:
        return self.client.call(run_id, "Repair Generator", payload, PatchProposal)


def validate_analysis(analysis: FailureAnalysis) -> None:
    files = set(analysis.files_to_modify)
    reasons = {item.file for item in analysis.reason_for_each_file}
    if files != reasons or len(files) != len(analysis.files_to_modify):
        raise ValueError("every requested repair file needs exactly one justification")
    for item in analysis.reason_for_each_file:
        if not all((item.reason, item.supporting_evidence, item.expected_effect,
                    item.required_verification)):
            raise ValueError("incomplete repair file justification")


def direct_approval_reason(root: Path, analysis: FailureAnalysis,
                           plan: MigrationPlan, verification: VerificationResult,
                           repository_analysis: RepositoryAnalysis | None = None) -> str | None:
    """Authorize only objective, scoped file changes; uncertain cases use Reviewer."""
    validate_analysis(analysis)
    if analysis.confidence < 0.8:
        return None
    failing = failure_text(verification)
    planned = set(plan.affected_files)
    for name in analysis.files_to_modify:
        path = (root / name).resolve()
        if not path.is_file() or not path.is_relative_to(root.resolve()):
            return None
        if not (name.startswith(("src/", "tests/")) or name == "pyproject.toml"):
            return None
        if name.endswith("/base.py"):
            return None
        if name in planned:
            if repository_analysis is not None and not (
                name in failing or any(test in failing for test in
                                       repository_analysis.related_tests.get(name, []))
            ):
                return None
            continue
        # A new scope item requires an explicit path in objective failure output.
        if name not in failing or name.endswith("/base.py"):
            return None
    return "all files exist in supported scope; planned files or explicit failing-output paths support modification"


def degradation_reason(before: VerificationResult, after: VerificationResult) -> str | None:
    formerly_passing = {check.name for check in before.checks if check.exit_code == 0}
    newly_failing = {check.name for check in after.checks if check.exit_code != 0}
    regressed_checks = sorted(formerly_passing & newly_failing)
    if regressed_checks:
        return "previously passing checks now fail: " + ", ".join(regressed_checks)
    def failed_tests(result: VerificationResult) -> set[str]:
        return {name for check in result.checks if check.name == "pytest"
                for name in re.findall(r"^FAILED (\S+)", check.output, re.MULTILINE)}
    new_tests = failed_tests(after) - failed_tests(before)
    if new_tests:
        return "new regression failures: " + ", ".join(sorted(new_tests))
    return None


def degraded(before: VerificationResult, after: VerificationResult) -> bool:
    return degradation_reason(before, after) is not None
