"""Native Responses schema enforcement and local validation."""

import io
import json
from pathlib import Path
from typing import Any

import pytest
from pytest import MonkeyPatch
from typing_extensions import Self

from patchpilot.workflow.model import ModelClient, SolBackend, strict_output_schema
from patchpilot.workflow.schema import MigrationPlan, PatchProposal
from patchpilot.workflow.store import RunStore

PLAN = {"summary": "Migrate", "planned_changes": [{"file": "pyproject.toml",
        "symbol": "dependencies", "reason": "v2", "change": "update pin",
        "expected_effect": "use v2"}], "affected_files": ["pyproject.toml"],
        "risks": [], "validation_plan": ["pytest"]}
PROPOSAL = {"changes": [{"path": "pyproject.toml", "content": "pydantic>=2"}],
            "rationale": "Update dependency"}


@pytest.mark.parametrize("contract,output", [(MigrationPlan, PLAN), (PatchProposal, PROPOSAL)])
def test_native_schema_and_typed_result(monkeypatch: MonkeyPatch, tmp_path: Path, contract: type[Any], output: dict[str, Any]) -> None:
    requests = []

    class Response(io.BytesIO):
        def __enter__(self) -> Self:
            return self

        def __exit__(self, *_: object) -> None:
            self.close()

    def fake_urlopen(request: Any, timeout: int) -> Response:
        requests.append(json.loads(request.data))
        return Response(json.dumps({"status": "completed", "output": [{"content": [
            {"type": "output_text", "text": json.dumps(output)}]}],
            "usage": {"input_tokens": 13, "output_tokens": 17}}).encode())

    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    store = RunStore(tmp_path / "runs.db")
    result = ModelClient(SolBackend(), store).call("test-run", contract.__name__, {}, contract)
    assert isinstance(result, contract)
    requested = requests[0]["text"]["format"]
    assert requested == {"type": "json_schema", "name": contract.__name__,
                         "strict": True, "schema": strict_output_schema(contract)}
    assert requested["schema"]["additionalProperties"] is False
    assert store.model_calls("test-run")[0].structured_output == output
    assert store.model_calls("test-run")[0].input_tokens == 13


def test_api_shaped_but_locally_invalid_output_records_failure(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    class Response(io.BytesIO):
        def __enter__(self) -> Self:
            return self

        def __exit__(self, *_: object) -> None:
            self.close()

    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr("urllib.request.urlopen", lambda *_args, **_kwargs: Response(
        json.dumps({"status": "completed", "output": [{"content": [
            {"type": "output_text", "text": json.dumps({"summary": "missing"})}]}],
            "usage": {"input_tokens": 3, "output_tokens": 4}}).encode()))
    store = RunStore(tmp_path / "runs.db")
    with pytest.raises(RuntimeError, match="invalid Migration Planner output"):
        ModelClient(SolBackend(), store, retries=0).call("bad-run", "Migration Planner", {}, MigrationPlan)
    call = store.model_calls("bad-run")[0]
    assert call.error and call.structured_output == {"summary": "missing"}
    assert call.input_tokens == 3 and call.output_tokens == 4
