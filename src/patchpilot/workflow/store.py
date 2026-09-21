"""Durable run, transition, and model-call records."""

import json
import sqlite3
from pathlib import Path

from .benchmarks import for_goal
from .schema import ModelCallRecord, RunRecord, State, StateTransitionRecord
from .state import transition


class RunStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS runs (
                    run_id TEXT PRIMARY KEY, data TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS transitions (
                    run_id TEXT NOT NULL, ordinal INTEGER PRIMARY KEY AUTOINCREMENT,
                    data TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS model_calls (
                    run_id TEXT NOT NULL, ordinal INTEGER PRIMARY KEY AUTOINCREMENT,
                    data TEXT NOT NULL
                );
            """)

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path)

    def save(self, run: RunRecord) -> None:
        with self._connect() as db:
            db.execute("INSERT OR REPLACE INTO runs VALUES (?, ?)",
                       (run.run_id, run.json()))

    def load(self, run_id: str) -> RunRecord:
        with self._connect() as db:
            row = db.execute("SELECT data FROM runs WHERE run_id=?", (run_id,)).fetchone()
        if row is None:
            raise KeyError(run_id)
        data = json.loads(row[0])
        # Older Prompt 2/3 records predate the generic family fields.
        family = for_goal(data["request"]["migration_goal"])
        if family is not None:
            data.setdefault("migration_family", family.name)
            data.setdefault("use_case", family.use_case)
        analysis = data.get("analysis")
        if analysis is not None and family is not None:
            analysis.pop("pydantic_version", None)
            if "v1_usages" in analysis:
                analysis["migration_api_usages"] = analysis.pop("v1_usages")
            analysis.setdefault("dependency_name", family.dependency_name)
            analysis.setdefault("dependency_version", "unknown")
            analysis.setdefault("migration_family", family.name)
            analysis.setdefault("migration_api_pattern", family.api_usage_pattern)
            analysis.setdefault("source_version", family.source_version)
            analysis.setdefault("target_version", family.target_version)
            analysis.setdefault("shared_base_symbols", list(family.shared_base_symbols))
        return RunRecord.parse_obj(data)

    def move(self, run: RunRecord, next_state: State, trigger: str,
             component: str) -> StateTransitionRecord:
        previous = None if not self.history(run.run_id) else run.current_state
        event = transition(previous, next_state, trigger, component, run.attempt_number)
        run.current_state = next_state
        with self._connect() as db:
            db.execute("INSERT INTO transitions (run_id, data) VALUES (?, ?)",
                       (run.run_id, event.json()))
            db.execute("INSERT OR REPLACE INTO runs VALUES (?, ?)",
                       (run.run_id, run.json()))
        return event

    def history(self, run_id: str) -> list[StateTransitionRecord]:
        with self._connect() as db:
            rows = db.execute("SELECT data FROM transitions WHERE run_id=? ORDER BY ordinal",
                              (run_id,)).fetchall()
        return [StateTransitionRecord.parse_raw(row[0]) for row in rows]

    def record_model_call(self, call: ModelCallRecord) -> None:
        with self._connect() as db:
            db.execute("INSERT INTO model_calls (run_id, data) VALUES (?, ?)",
                       (call.run_id, call.json()))

    def model_calls(self, run_id: str) -> list[ModelCallRecord]:
        with self._connect() as db:
            rows = db.execute("SELECT data FROM model_calls WHERE run_id=? ORDER BY ordinal",
                              (run_id,)).fetchall()
        return [ModelCallRecord.parse_raw(row[0]) for row in rows]
