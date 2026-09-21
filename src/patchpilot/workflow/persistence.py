"""SQLite tool boundary for Prompt 5 workflow persistence."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import TypeVar

from .schema import (
    ModelCallRecord,
    RetryRecord,
    RunRecord,
    State,
    StateTransitionRecord,
    SystemFailureRecord,
)
from .state import transition
from .store import RunStore

T = TypeVar("T")


class PersistenceHalt(Exception):
    """A database failure stopped the run; the in-memory record is available."""

    def __init__(self, run: RunRecord, cause: sqlite3.Error) -> None:
        super().__init__(str(cause))
        self.run = run
        self.cause = cause


class PersistenceBoundary(RunStore):
    """Wrap one RunStore without changing its durable schema or callers."""

    def __init__(self, raw: RunStore, enabled: Callable[[], bool], retries: int = 1) -> None:
        self.raw = raw
        self.path: Path = raw.path
        self.enabled = enabled
        self.retries = retries
        self.active_run: RunRecord | None = None
        self.in_memory_history: list[StateTransitionRecord] = []
        self.seeded_initial_runs: set[str] = set()

    def _ensure_initial_transition(self, run: RunRecord) -> None:
        """A failed first save may leave no durable INITIAL → RECEIVED event."""
        if run.current_state != State.RECEIVED:
            return
        try:
            if self.raw.history(run.run_id):
                return
            self.raw.move(run, State.RECEIVED, "request_created", "Orchestrator")
            self.seeded_initial_runs.add(run.run_id)
        except sqlite3.Error:
            if not self.in_memory_history:
                self.in_memory_history.append(transition(
                    None, State.RECEIVED, "request_created", "Orchestrator",
                    run.attempt_number))
            run.current_state = State.RECEIVED
            self.seeded_initial_runs.add(run.run_id)

    def _move_safely(self, run: RunRecord, state: State, trigger: str,
                     previous: State | None = None) -> None:
        origin = previous if previous is not None else run.current_state
        error_origin = run.error_origin_state
        try:
            self.raw.move(run, state, trigger, "SQLite RunStore")
        except sqlite3.Error:
            # The same database may still be unavailable. Keep a validated event
            # in memory; never call the boundary again from this fallback.
            run.current_state = origin
            run.error_origin_state = error_origin
            event = transition(origin, state, trigger, "SQLite RunStore",
                               run.attempt_number, recovery_state=run.error_origin_state)
            self.in_memory_history.append(event)
            if state in (State.TOOL_ERROR, State.MODEL_ERROR, State.ENVIRONMENT_ERROR):
                run.error_origin_state = origin
            elif origin in (State.TOOL_ERROR, State.MODEL_ERROR, State.ENVIRONMENT_ERROR):
                run.error_origin_state = None
            run.current_state = state

    def _call(self, operation: str, action: Callable[[], T],
              run: RunRecord | None = None) -> T:
        if not self.enabled():
            return action()
        current = run or self.active_run
        for attempt in range(1, self.retries + 2):
            previous = current.current_state if current is not None else None
            error_origin = current.error_origin_state if current is not None else None
            try:
                result = action()
                if current is not None and attempt > 1:
                    current.retries[-1].recovered = True
                    current.system_failures[-1].recovered = True
                    try:
                        self.raw.save(current)
                    except sqlite3.Error:
                        # The operation already succeeded; keep the recovery record in memory.
                        pass
                return result
            except sqlite3.Error as exc:
                if current is None:
                    raise
                # RunStore.move mutates the record before its SQL transaction.
                assert previous is not None
                current.current_state = previous
                current.error_origin_state = error_origin
                stamp = datetime.now(timezone.utc).isoformat()
                current.system_failures.append(SystemFailureRecord(
                    component="SQLite RunStore", category="TOOL_ERROR",
                    operation=operation, previous_state=previous.value if previous else None,
                    error_type=type(exc).__name__, error_message=str(exc),
                    retry_count=attempt, recovered=False, timestamp=stamp))
                current.retries.append(RetryRecord(
                    component="SQLite RunStore", operation=operation,
                    previous_state=previous.value if previous else None,
                    error_type=type(exc).__name__, error_message=str(exc),
                    retry_count=attempt, recovered=False, timestamp=stamp))
                if current.current_state == State.FAILED_SYSTEM:
                    raise PersistenceHalt(current, exc) from exc
                if current.current_state == State.RECEIVED:
                    self._ensure_initial_transition(current)
                if current.current_state != State.TOOL_ERROR:
                    self._move_safely(current, State.TOOL_ERROR,
                                      f"sqlite_{operation}_failed")
                if attempt <= self.retries:
                    self._move_safely(current, previous, "sqlite_retry", State.TOOL_ERROR)
                    continue
                self._move_safely(current, State.FAILED_SYSTEM,
                                  "sqlite_retries_exhausted")
                current.final_status = State.FAILED_SYSTEM.value
                current.terminal_reason = f"SQLite {operation}: {type(exc).__name__}: {exc}"
                current.ended_at = datetime.now(timezone.utc).isoformat()
                try:
                    self.raw.save(current)
                except sqlite3.Error:
                    pass
                raise PersistenceHalt(current, exc) from exc
        raise AssertionError("unreachable")

    def save(self, run: RunRecord) -> None:
        self.active_run = run
        self._call("save", lambda: self.raw.save(run), run)

    def load(self, run_id: str) -> RunRecord:
        result = self._call("load", lambda: self.raw.load(run_id))
        if self.active_run is None or self.active_run.run_id != run_id:
            self.active_run = result
        return result

    def move(self, run: RunRecord, next_state: State, trigger: str,
             component: str) -> StateTransitionRecord:
        self.active_run = run
        if next_state == State.RECEIVED and run.run_id in self.seeded_initial_runs:
            history = self._call("history", lambda: self.raw.history(run.run_id), run)
            self.seeded_initial_runs.remove(run.run_id)
            if history:
                return history[0]
        return self._call("move", lambda: self.raw.move(run, next_state, trigger, component), run)

    def history(self, run_id: str) -> list[StateTransitionRecord]:
        return self._call("history", lambda: self.raw.history(run_id))

    def record_model_call(self, call: ModelCallRecord) -> None:
        self._call("record_model_call", lambda: self.raw.record_model_call(call))

    def model_calls(self, run_id: str) -> list[ModelCallRecord]:
        return self._call("model_calls", lambda: self.raw.model_calls(run_id))
