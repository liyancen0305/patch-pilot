"""Invalid model output fails at the central state boundary."""

from pathlib import Path

import pytest

from patchpilot.workflow import RunStore, VerificationRunner, Workflow
from patchpilot.workflow.model import ModelClient
from patchpilot.workflow.schema import State

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures/pydantic_v1_app"


class MalformedBackend:
    model = "malformed-test-double"

    def complete(self, component: str, payload: dict[str, object],
                 schema: type[object]) -> tuple[dict[str, object], int, int]:
        return {"summary": "missing required fields"}, 1, 1


def test_invalid_plan_persists_model_error(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "runs.db")
    client = ModelClient(MalformedBackend(), store, retries=1)
    workflow = Workflow(store, client, VerificationRunner())
    with pytest.raises(RuntimeError, match="invalid Migration Planner output"):
        workflow.run(FIXTURE, tmp_path / "artifacts")
    import sqlite3

    with sqlite3.connect(store.path) as db:
        run_id = db.execute("SELECT run_id FROM runs").fetchone()[0]
    assert store.load(run_id).current_state == State.MODEL_ERROR
    assert store.history(run_id)[-1].next_state == State.MODEL_ERROR
    assert len(store.model_calls(run_id)) == 2
    assert all(call.error for call in store.model_calls(run_id))
