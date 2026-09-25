"""Validated contracts shared by the migration workflow."""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic.v1 import BaseModel, Field


class StrictModel(BaseModel):
    class Config:
        extra = "forbid"


class State(str, Enum):
    RECEIVED = "RECEIVED"
    SCOPE_CHECK = "SCOPE_CHECK"
    CAPABILITY_CLASSIFYING = "CAPABILITY_CLASSIFYING"
    VERIFICATION_CAPABILITY_CHECK = "VERIFICATION_CAPABILITY_CHECK"
    UNSUPPORTED = "UNSUPPORTED"
    SCOPE_VIOLATION = "SCOPE_VIOLATION"
    VERIFICATION_FAILURE = "VERIFICATION_FAILURE"
    ANALYZING_REPO = "ANALYZING_REPO"
    CONTEXT_BUILDING = "CONTEXT_BUILDING"
    PLANNING = "PLANNING"
    PATCH_GENERATING = "PATCH_GENERATING"
    PATCHING_SANDBOX = "PATCHING_SANDBOX"
    VERIFYING_SANDBOX = "VERIFYING_SANDBOX"
    VERIFIED_PATCH_READY = "VERIFIED_PATCH_READY"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    APPROVED = "APPROVED"
    APPLYING_TO_TARGET_BRANCH = "APPLYING_TO_TARGET_BRANCH"
    VERIFYING_TARGET_BRANCH = "VERIFYING_TARGET_BRANCH"
    READY_FOR_PR = "READY_FOR_PR"
    ANALYZING_FAILURE = "ANALYZING_FAILURE"
    GATHERING_ADDITIONAL_CONTEXT = "GATHERING_ADDITIONAL_CONTEXT"
    REPAIR_PROPOSED = "REPAIR_PROPOSED"
    AWAITING_REVIEW = "AWAITING_REVIEW"
    REPAIR_APPROVED = "REPAIR_APPROVED"
    REPAIR_REJECTED = "REPAIR_REJECTED"
    REPAIRING = "REPAIRING"
    NEEDS_HUMAN_REVIEW = "NEEDS_HUMAN_REVIEW"
    MODEL_ERROR = "MODEL_ERROR"
    TOOL_ERROR = "TOOL_ERROR"
    ENVIRONMENT_ERROR = "ENVIRONMENT_ERROR"
    FAILED_SYSTEM = "FAILED_SYSTEM"


class MigrationRequest(StrictModel):
    repository: str
    migration_goal: str
    language: str = "Python"
    constraints: list[str] = Field(default_factory=lambda: [
        "remain in Python", "preserve existing behavior", "do not modify unrelated files",
        "do not deploy automatically", "do not merge automatically",
    ])


class CapabilityDecision(StrictModel):
    supported: bool
    reasons: list[str]


class CapabilityClassification(StrictModel):
    classification: Literal["SUPPORTED_MIGRATION", "UNSUPPORTED", "NEED_MORE_INFORMATION"]
    reason: str = Field(min_length=1)
    detected_migration_type: str
    scope_risk: str
    missing_information: list[str]


class UnsupportedDecision(StrictModel):
    reason: str
    detected_request_type: str
    violated_scope_rule: str
    supported_alternative: str | None = None


class VerificationCapabilityResult(StrictModel):
    sufficient: bool
    checks: dict[str, bool]
    reasons: list[str]


class GuardrailViolation(StrictModel):
    rule: str
    reason: str
    component: str
    file: str | None = None


class RetryRecord(StrictModel):
    component: str
    operation: str | None = None
    previous_state: str | None = None
    error_type: str
    retry_count: int
    error_message: str
    recovered: bool
    timestamp: str


class SystemFailureRecord(StrictModel):
    component: str
    operation: str | None = None
    previous_state: str | None = None
    category: Literal["MODEL_ERROR", "TOOL_ERROR", "ENVIRONMENT_ERROR"]
    error_type: str
    error_message: str
    retry_count: int
    recovered: bool
    timestamp: str


class AllowedTestRewrite(StrictModel):
    old_api: str
    new_api: str
    reason: str


class AllowedFileRule(StrictModel):
    path: str
    category: str
    reason: str
    migration_relevant: bool


class AllowedModificationScope(StrictModel):
    migration_family: str
    files: dict[str, AllowedFileRule]
    approved_files: list[str]


class GuardrailDecisionRecord(StrictModel):
    file: str
    component: str
    decision: Literal["ALLOWED", "REJECTED"]
    category: str | None
    reason: str
    test_rewrite_rules: list[str] = Field(default_factory=list)
    timestamp: str


class RepositoryAnalysis(StrictModel):
    dependency_file: str
    dependency_files: list[str] = Field(default_factory=list)
    dependency_name: str
    dependency_version: str
    source_version: str
    target_version: str
    migration_family: str
    migration_api_pattern: str
    shared_base_symbols: list[str]
    source_files: list[str]
    test_files: list[str]
    configuration_files: list[str]
    imports: dict[str, list[str]]
    classes: dict[str, list[str]]
    decorators: dict[str, list[str]]
    migration_api_usages: dict[str, list[str]]
    related_tests: dict[str, list[str]]
    evidence: dict[str, list[str]] = Field(default_factory=dict)


class ContextItem(StrictModel):
    path: str
    location: str
    symbol: str
    start_line: int
    end_line: int
    content: str
    score: int
    reason: str
    token_estimate: int


class ContextBundle(StrictModel):
    items: list[ContextItem]
    total_token_estimate: int
    max_files: int
    max_snippets: int
    max_context_tokens: int


class PlannedChange(StrictModel):
    file: str
    symbol: str
    reason: str
    change: str
    expected_effect: str


class MigrationPlan(StrictModel):
    summary: str
    planned_changes: list[PlannedChange] = Field(min_items=1)
    affected_files: list[str] = Field(min_items=1)
    risks: list[str]
    validation_plan: list[str] = Field(min_items=1)


class FileChange(StrictModel):
    path: str
    content: str


class PatchProposal(StrictModel):
    changes: list[FileChange] = Field(min_items=1)
    rationale: str


class PatchResult(StrictModel):
    pre_snapshot: str
    post_snapshot: str
    changed_files: list[str]
    diff: str
    sha256: str


class VerificationCheck(StrictModel):
    name: str
    command: list[str]
    exit_code: int
    output: str


class VerificationResult(StrictModel):
    passed: bool
    checks: list[VerificationCheck]


class ApprovalDecision(StrictModel):
    decision: str
    actor: str
    timestamp: str


class RepairFileReason(StrictModel):
    file: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    supporting_evidence: str = Field(min_length=1)
    expected_effect: str = Field(min_length=1)
    required_verification: str = Field(min_length=1)


class FailureAnalysis(StrictModel):
    failure_type: str = Field(min_length=1)
    likely_root_cause: str = Field(min_length=1)
    supporting_evidence: list[str] = Field(min_items=1)
    proposed_repair: str = Field(min_length=1)
    files_to_modify: list[str] = Field(min_items=1)
    reason_for_each_file: list[RepairFileReason] = Field(min_items=1)
    additional_context_needed: list[str]
    confidence: float = Field(ge=0, le=1)


class ReviewDecision(StrictModel):
    decision: Literal["APPROVE", "REJECT", "NEED_MORE_EVIDENCE"]
    reason: str = Field(min_length=1)
    supporting_evidence: list[str] = Field(min_items=1)
    risk: str = Field(min_length=1)
    additional_context_needed: list[str]
    required_verification: list[str]


class ContextExpansionRecord(StrictModel):
    attempt_number: int
    previous_context: ContextBundle
    new_context: ContextBundle
    expansion_reason: str


class RepairAttemptRecord(StrictModel):
    attempt_number: int
    failure_analysis: FailureAnalysis | None = None
    repair_decision_path: str | None = None
    approval_reason: str | None = None
    reviewer_decisions: list[ReviewDecision] = Field(default_factory=list)
    stable_snapshot_id: str | None = None
    last_verified_stable_snapshot_id: str | None = None
    repair_base_checkpoint_id: str | None = None
    candidate_checkpoint_id: str | None = None
    repair_diff: str | None = None
    proposal: PatchProposal | None = None
    verification_before: VerificationResult | None = None
    verification_after: VerificationResult | None = None
    degraded: bool = False
    degraded_reason: str | None = None
    rollback_result: str | None = None
    rollback_target: str | None = None
    rollback_reason: str | None = None


class StateTransitionRecord(StrictModel):
    previous_state: str
    trigger: str
    component: str
    next_state: State
    attempt_number: int = 1
    timestamp: str


class ModelCallRecord(StrictModel):
    run_id: str
    attempt_number: int = 1
    component: str
    model: str
    prompt_name: str
    prompt_version: str
    input_metadata: dict[str, Any]
    input_tokens: int
    output_tokens: int
    latency_seconds: float
    estimated_cost_usd: float | None
    structured_output: dict[str, Any] | None
    error: str | None
    timestamp: str


class RunRecord(StrictModel):
    run_id: str
    request: MigrationRequest
    current_state: State
    prompt_name: str = "02_happy_path_e2e"
    prompt_version: str = "v1.1"
    attempt_number: int = 1
    error_origin_state: State | None = None
    repository_identifiers: dict[str, str]
    use_case: int
    migration_family: str
    model_type: str = "unknown"
    capability_decision: CapabilityDecision | None = None
    scope_rule: str | None = None
    capability_classification: CapabilityClassification | None = None
    unsupported_decision: UnsupportedDecision | None = None
    verification_capability: VerificationCapabilityResult | None = None
    guardrail_violations: list[GuardrailViolation] = Field(default_factory=list)
    allowed_modification_scope: AllowedModificationScope | None = None
    guardrail_decisions: list[GuardrailDecisionRecord] = Field(default_factory=list)
    system_failures: list[SystemFailureRecord] = Field(default_factory=list)
    retries: list[RetryRecord] = Field(default_factory=list)
    failure_classification: str | None = None
    terminal_reason: str | None = None
    analysis: RepositoryAnalysis | None = None
    context: ContextBundle | None = None
    plan: MigrationPlan | None = None
    proposal: PatchProposal | None = None
    patch: PatchResult | None = None
    sandbox_verification: VerificationResult | None = None
    approval: ApprovalDecision | None = None
    target_verification: VerificationResult | None = None
    target_branch: str | None = None
    repair_attempts: list[RepairAttemptRecord] = Field(default_factory=list)
    context_expansions: list[ContextExpansionRecord] = Field(default_factory=list)
    expansion_count: int = 0
    expansion_limit: int = 2
    unresolved_context_request: list[str] = Field(default_factory=list)
    reason_for_escalation: str | None = None
    failure_analyses: list[FailureAnalysis] = Field(default_factory=list)
    review_history: list[ReviewDecision] = Field(default_factory=list)
    repair_decisions: list[str] = Field(default_factory=list)
    final_status: str | None = None
    started_at: str
    ended_at: str | None = None
