"""The single authoritative transition policy."""

import itertools
from datetime import datetime, timezone

from .schema import State, StateTransitionRecord

HAPPY_PATH = (
    State.RECEIVED, State.SCOPE_CHECK, State.ANALYZING_REPO,
    State.CONTEXT_BUILDING, State.PLANNING, State.PATCH_GENERATING,
    State.PATCHING_SANDBOX, State.VERIFYING_SANDBOX,
    State.VERIFIED_PATCH_READY, State.AWAITING_APPROVAL, State.APPROVED,
    State.APPLYING_TO_TARGET_BRANCH, State.VERIFYING_TARGET_BRANCH,
    State.READY_FOR_PR,
)
ALLOWED: dict[State | None, frozenset[State]] = {
    None: frozenset({State.RECEIVED}),
    **{a: frozenset({b}) for a, b in itertools.pairwise(HAPPY_PATH)},
    State.READY_FOR_PR: frozenset(),
}
for _state in (State.PLANNING, State.PATCH_GENERATING):
    ALLOWED[_state] |= {State.MODEL_ERROR}
for _state in HAPPY_PATH[:-1]:
    ALLOWED[_state] |= {State.TOOL_ERROR, State.ENVIRONMENT_ERROR, State.FAILED_SYSTEM}
for _state in (State.MODEL_ERROR, State.TOOL_ERROR, State.ENVIRONMENT_ERROR, State.FAILED_SYSTEM):
    ALLOWED[_state] = frozenset()


def transition(previous: State | None, next_state: State, trigger: str,
               component: str, attempt_number: int = 1) -> StateTransitionRecord:
    if next_state not in ALLOWED[previous]:
        raise ValueError(f"invalid transition: {previous} -> {next_state}")
    if attempt_number not in (1, 2, 3):
        raise ValueError("attempt number must be 1, 2, or 3")
    if not trigger or not component:
        raise ValueError("transition trigger and component are required")
    return StateTransitionRecord(
        previous_state=previous.value if previous else "INITIAL",
        trigger=trigger, component=component, next_state=next_state,
        attempt_number=attempt_number,
        timestamp=datetime.now(timezone.utc).isoformat(),
    )
