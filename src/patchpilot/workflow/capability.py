"""Deterministic Prompt 5 request, verification, and proposal guardrails."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from .benchmarks import MigrationFamily, for_goal
from .guardrails import file_scope_reason, validate_test_change
from .schema import (
    AllowedModificationScope,
    AllowedTestRewrite,
    FailureAnalysis,
    GuardrailDecisionRecord,
    GuardrailViolation,
    MigrationPlan,
    MigrationRequest,
    PatchProposal,
    UnsupportedDecision,
    VerificationCapabilityResult,
    VerificationResult,
)

_UNSUPPORTED: tuple[tuple[str, str, str], ...] = (
    (r"\b(?:python\s*(?:to|→)\s*java|rewrite\s+in\s+java|cross.language)\b",
     "cross_language_rewrite", "same_language_only"),
    (r"\b(?:new\s+(?:payment\s+)?feature|add\s+(?:a\s+)?payment\s+feature)\b",
     "new_feature", "migration_only"),
    (r"\b(?:architectural\s+redesign|redesign\s+the\s+architecture|rewrite\s+the\s+system)\b",
     "architecture_redesign", "migration_only"),
    (r"\b(?:deploy\s+(?:automatically|to\s+production)|production\s+deployment)\b",
     "production_deployment", "no_automatic_deployment"),
    (r"\b(?:drop\s+(?:the\s+)?production\s+database|destructive\s+production\s+(?:db|database))\b",
     "destructive_database_operation", "no_destructive_production_actions"),
)
_FORBIDDEN_ACTION = re.compile(
    r"\b(?:deploy\s+(?:to\s+production|automatically)|drop\s+(?:the\s+)?production\s+database|"
    r"delete\s+(?:failing\s+)?tests?|weaken\s+assertions?|"
    r"change\s+expected\s+values?|architectural\s+redesign)\b", re.IGNORECASE,
)
def classify_request(request: MigrationRequest, allowed_repositories: tuple[Path, ...]
                     ) -> tuple[str, UnsupportedDecision | None]:
    """Return SUPPORTED, UNSUPPORTED, or AMBIGUOUS without calling a model."""
    goal = request.migration_goal.strip()
    for pattern, request_type, rule in _UNSUPPORTED:
        if re.search(pattern, goal, re.IGNORECASE):
            return "UNSUPPORTED", UnsupportedDecision(
                reason=f"Request violates {rule}", detected_request_type=request_type,
                violated_scope_rule=rule,
                supported_alternative="Request a supported same-language dependency/API migration",
            )
    if request.language.lower() != "python":
        return "UNSUPPORTED", UnsupportedDecision(
            reason="Only Python same-language migrations are supported",
            detected_request_type="unsupported_language",
            violated_scope_rule="python_only",
        )
    repository = Path(request.repository).resolve()
    if repository not in tuple(root.resolve() for root in allowed_repositories):
        return "UNSUPPORTED", UnsupportedDecision(
            reason="Repository is outside the permitted request workspace",
            detected_request_type="outside_workspace",
            violated_scope_rule="permitted_repository_only",
        )
    if for_goal(goal) is not None:
        return "SUPPORTED", None
    return "AMBIGUOUS", None


def verification_capability(root: Path, family: MigrationFamily,
                            capability_reasons: list[str]) -> VerificationCapabilityResult:
    """Require objective checks before model planning."""
    checks = {
        "migration_specific": bool(family.deprecated_api_pattern and family.target_pin),
        "regression_tests": any((root / "tests").rglob("test_*.py")),
        "pytest": not any("pytest unavailable" in item for item in capability_reasons),
        "mypy": not any("mypy unavailable" in item for item in capability_reasons),
        "ruff": not any("ruff unavailable" in item for item in capability_reasons),
        "runtime_import": bool(family.runtime_check),
        "dependency_version": not any("target dependency unavailable" in item
                                      for item in capability_reasons),
    }
    reasons = [f"{name} unavailable" for name, available in checks.items() if not available]
    return VerificationCapabilityResult(sufficient=not reasons, checks=checks,
                                        reasons=reasons)


def _scope_violation(root: Path, scope: AllowedModificationScope,
                     path: str, component: str,
                     require_approval: bool = True) -> GuardrailViolation | None:
    reason = file_scope_reason(root, scope, path, require_approval)
    if reason is None:
        return None
    rule = ("production_credentials" if "credential or secret" in reason else
            "prohibited_deployment_file" if "production or deployment" in reason else
            "repository_scope")
    return GuardrailViolation(rule=rule, reason=reason, component=component, file=path)


def _decision(path: str, component: str, decision: Literal["ALLOWED", "REJECTED"],
              scope: AllowedModificationScope, reason: str,
              rewrites: list[AllowedTestRewrite] | None = None) -> GuardrailDecisionRecord:
    category = scope.files[path].category if path in scope.files else None
    return GuardrailDecisionRecord(
        file=path, component=component, decision=decision, category=category,
        reason=reason, test_rewrite_rules=[rule.reason for rule in rewrites or []],
        timestamp=datetime.now(timezone.utc).isoformat(),
    )


def plan_violation(root: Path, plan: MigrationPlan,
                   scope: AllowedModificationScope,
                   decisions: list[GuardrailDecisionRecord] | None = None
                   ) -> GuardrailViolation | None:
    for item in plan.planned_changes:
        violation = _scope_violation(root, scope, item.file, "Migration Planner", False)
        if violation:
            if decisions is not None:
                decisions.append(_decision(item.file, "Migration Planner", "REJECTED",
                                           scope, violation.reason))
            return violation
        if _FORBIDDEN_ACTION.search(item.change):
            return GuardrailViolation(rule="prohibited_action", reason=item.change,
                                      component="Migration Planner", file=item.file)
    for path in plan.affected_files:
        violation = _scope_violation(root, scope, path, "Migration Planner", False)
        if violation:
            if decisions is not None:
                decisions.append(_decision(path, "Migration Planner", "REJECTED",
                                           scope, violation.reason))
            return violation
        if decisions is not None:
            rule = scope.files[path]
            decisions.append(_decision(path, "Migration Planner", "ALLOWED",
                                       scope, rule.reason))
    return None


def proposal_violation(root: Path, proposal: PatchProposal,
                       component: str, scope: AllowedModificationScope,
                       rewrites: tuple[AllowedTestRewrite, ...] = (),
                       decisions: list[GuardrailDecisionRecord] | None = None
                       ) -> GuardrailViolation | None:
    for item in proposal.changes:
        violation = _scope_violation(root, scope, item.path, component)
        if violation:
            if decisions is not None:
                decisions.append(_decision(item.path, component, "REJECTED",
                                           scope, violation.reason))
            return violation
        path = root / item.path
        previous = path.read_text()
        allowed_rewrites: list[AllowedTestRewrite] = []
        if scope.files[item.path].category == "test":
            try:
                allowed_rewrites = validate_test_change(previous, item.content, rewrites)
            except ValueError as exc:
                if decisions is not None:
                    decisions.append(_decision(item.path, component, "REJECTED",
                                               scope, str(exc)))
                return GuardrailViolation(rule="regression_test_protection", reason=str(exc),
                                          component=component, file=item.path)
        added = set(item.content.splitlines()) - set(previous.splitlines())
        if any(_FORBIDDEN_ACTION.search(line) for line in added):
            if decisions is not None:
                decisions.append(_decision(item.path, component, "REJECTED",
                                           scope, "unsafe action in patch"))
            return GuardrailViolation(rule="prohibited_action", reason="unsafe action in patch",
                                      component=component, file=item.path)
        if decisions is not None:
            decisions.append(_decision(item.path, component, "ALLOWED", scope,
                                       scope.files[item.path].reason, allowed_rewrites))
    return None


def failure_analysis_violation(root: Path, analysis: FailureAnalysis,
                               scope: AllowedModificationScope) -> GuardrailViolation | None:
    for path in analysis.files_to_modify:
        violation = _scope_violation(root, scope, path, "Failure Analyzer", False)
        if violation:
            return violation
    if _FORBIDDEN_ACTION.search(analysis.proposed_repair):
        return GuardrailViolation(rule="prohibited_action", reason=analysis.proposed_repair,
                                  component="Failure Analyzer")
    return None


def verification_failure_kind(result: VerificationResult,
                              dependency_check_name: str) -> str:
    """Only completed checks reporting application errors are repairable."""
    for check in result.checks:
        if check.exit_code == 0:
            continue
        if check.name == dependency_check_name:
            return "ENVIRONMENT_ERROR"
        output = check.output.lower()
        if check.exit_code in (126, 127) or re.search(
                r"no module named (?:pytest|mypy|ruff|packaging)|command not found|"
                r"cannot execute|permission denied|failed to start", output):
            return "ENVIRONMENT_ERROR"
    return "VERIFICATION_FAILURE"
