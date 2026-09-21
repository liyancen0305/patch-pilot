"""SQLite failures use Prompt 5 tool-error routing without recursion."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

import pytest
from test_happy_path import FIXTURE, V2_PYTHON
from test_prompt5_guardrails import GOAL, ControlledBackend, FastVerifier, request

from patchpilot.workflow import RunStore, Workflow
from patchpilot.workflow.model import ModelClient
from patchpilot.workflow.schema import State


def run_with(store: RunStore, root: Path, model: ControlledBackend | None = None
             ) -> tuple[Any, Workflow, ControlledBackend]:
    backend = model or ControlledBackend()
    workflow = Workflow(store, ModelClient(backend, store), FastVerifier(V2_PYTHON))
    run = workflow.run(FIXTURE, root / "artifacts", request=request(GOAL))
    return run, workflow, backend


def test_permanent_save_failure_stops_without_repair(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = RunStore(tmp_path / "runs.db")
    original = store.save
    count = 0

    def failed_save(run: Any) -> None:
        nonlocal count
        count += 1
        if count >= 5:
            raise sqlite3.OperationalError("database is locked")
        original(run)

    monkeypatch.setattr(store, "save", failed_save)
    run, _, model = run_with(store, tmp_path)
    assert run.current_state == State.FAILED_SYSTEM
    assert run.final_status == State.FAILED_SYSTEM.value
    history = [event.next_state for event in store.history(run.run_id)]
    assert history[-2:] == [State.TOOL_ERROR, State.FAILED_SYSTEM]
    assert history.count(State.TOOL_ERROR) == 2
    assert len([item for item in run.system_failures if item.operation == "save"]) == 2
    assert run.system_failures[-1].previous_state
    assert run.system_failures[-1].error_type == "OperationalError"
    assert "database is locked" in run.terminal_reason
    assert "Failure Analyzer" not in model.components


def test_tool_error_record_failure_uses_in_memory_fallback(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = RunStore(tmp_path / "runs.db")
    original_save = store.save
    original_move = store.move
    count = 0
    tool_error_moves = 0

    def failed_save(run: Any) -> None:
        nonlocal count
        count += 1
        if count >= 5:
            raise sqlite3.DatabaseError("disk I/O failure")
        original_save(run)

    def failed_move(run: Any, state: State, trigger: str, component: str) -> Any:
        nonlocal tool_error_moves
        if state == State.TOOL_ERROR:
            tool_error_moves += 1
            raise sqlite3.DatabaseError("cannot record tool error")
        return original_move(run, state, trigger, component)

    monkeypatch.setattr(store, "save", failed_save)
    monkeypatch.setattr(store, "move", failed_move)
    run, workflow, model = run_with(store, tmp_path)
    assert run.current_state == State.FAILED_SYSTEM
    assert tool_error_moves == 2
    assert [item.next_state for item in workflow.store.in_memory_history] == [
        State.TOOL_ERROR, State.TOOL_ERROR
    ]
    assert run.system_failures[-1].error_type == "DatabaseError"
    assert run.system_failures[-1].error_message == "disk I/O failure"
    assert "Failure Analyzer" not in model.components


def test_transition_write_retries_to_previous_state(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = RunStore(tmp_path / "runs.db")
    original = store.move
    failed = False

    def failed_move(run: Any, state: State, trigger: str, component: str) -> Any:
        nonlocal failed
        if state == State.CONTEXT_BUILDING and not failed:
            failed = True
            raise sqlite3.DatabaseError("transition write failed")
        return original(run, state, trigger, component)

    monkeypatch.setattr(store, "move", failed_move)
    run, _, model = run_with(store, tmp_path)
    assert run.current_state == State.READY_FOR_PR
    history = store.history(run.run_id)
    index = next(i for i, item in enumerate(history) if item.next_state == State.TOOL_ERROR)
    assert history[index].previous_state == State.ANALYZING_REPO.value
    assert history[index + 1].next_state == State.ANALYZING_REPO
    assert history[index + 2].next_state == State.CONTEXT_BUILDING
    assert run.system_failures[0].operation == "move"
    assert run.system_failures[0].recovered
    assert "Failure Analyzer" not in model.components


def test_telemetry_write_retries_as_tool_failure(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = RunStore(tmp_path / "runs.db")
    original = store.record_model_call
    failed = False

    def failed_telemetry(call: Any) -> None:
        nonlocal failed
        if not failed:
            failed = True
            raise sqlite3.OperationalError("telemetry insert failed")
        original(call)

    monkeypatch.setattr(store, "record_model_call", failed_telemetry)
    run, _, model = run_with(store, tmp_path)
    assert run.current_state == State.READY_FOR_PR
    assert run.system_failures[0].operation == "record_model_call"
    assert run.system_failures[0].recovered
    assert len(store.model_calls(run.run_id)) == 2
    assert "Failure Analyzer" not in model.components


def test_final_status_save_failure_recovers_without_false_success(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = RunStore(tmp_path / "runs.db")
    original = store.save
    failed = False

    def failed_final_save(run: Any) -> None:
        nonlocal failed
        if run.current_state == State.READY_FOR_PR and not failed:
            failed = True
            raise sqlite3.OperationalError("final status write failed")
        original(run)

    monkeypatch.setattr(store, "save", failed_final_save)
    run, _, _ = run_with(store, tmp_path)
    assert run.current_state == State.READY_FOR_PR
    path = [item.next_state for item in store.history(run.run_id)]
    assert path[-2:] == [State.TOOL_ERROR, State.READY_FOR_PR]
    assert run.system_failures[-1].operation == "save"
    assert run.system_failures[-1].recovered


def test_first_run_save_failure_recovers_with_initial_transition(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = RunStore(tmp_path / "runs.db")
    original = store.save
    failed = False

    def failed_first_save(run: Any) -> None:
        nonlocal failed
        if not failed:
            failed = True
            raise sqlite3.OperationalError("initial insert failed")
        original(run)

    monkeypatch.setattr(store, "save", failed_first_save)
    run, _, _ = run_with(store, tmp_path)
    assert run.current_state == State.READY_FOR_PR
    path = [item.next_state for item in store.history(run.run_id)]
    assert path[:3] == [State.RECEIVED, State.TOOL_ERROR, State.RECEIVED]
    assert run.system_failures[0].error_message == "initial insert failed"
