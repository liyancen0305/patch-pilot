"""Validated contracts shared by the migration workflow."""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class StrictModel(BaseModel):
    class Config:
        extra = "forbid"


class State(str, Enum):
    RECEIVED = "RECEIVED"
    SCOPE_CHECK = "SCOPE_CHECK"
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
    MODEL_ERROR = "MODEL_ERROR"
    TOOL_ERROR = "TOOL_ERROR"
    ENVIRONMENT_ERROR = "ENVIRONMENT_ERROR"
    FAILED_SYSTEM = "FAILED_SYSTEM"


class MigrationRequest(StrictModel):
    repository: str
    migration_goal: str = "Upgrade Pydantic v1 to Pydantic v2"
    language: str = "Python"
    constraints: list[str] = Field(default_factory=lambda: [
        "remain in Python", "preserve existing behavior", "do not modify unrelated files",
        "do not deploy automatically", "do not merge automatically",
    ])


class CapabilityDecision(StrictModel):
    supported: bool
    reasons: list[str]


class RepositoryAnalysis(StrictModel):
    dependency_file: str
    pydantic_version: str
    source_files: list[str]
    test_files: list[str]
    configuration_files: list[str]
    imports: dict[str, list[str]]
    classes: dict[str, list[str]]
    decorators: dict[str, list[str]]
    v1_usages: dict[str, list[str]]
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
    repository_identifiers: dict[str, str]
    analysis: RepositoryAnalysis | None = None
    context: ContextBundle | None = None
    plan: MigrationPlan | None = None
    proposal: PatchProposal | None = None
    patch: PatchResult | None = None
    sandbox_verification: VerificationResult | None = None
    approval: ApprovalDecision | None = None
    target_verification: VerificationResult | None = None
    target_branch: str | None = None
    final_status: str | None = None
    started_at: str
    ended_at: str | None = None
