"""Final prompt contracts and backward-compatible run metadata."""

import json
from pathlib import Path

from patchpilot.workflow.model import ModelClient
from patchpilot.workflow.schema import MigrationRequest, PatchProposal, RunRecord, State
from patchpilot.workflow.store import RunStore

ROOT = Path(__file__).resolve().parents[1]


class ProposalBackend:
    model = "schema-test-double"

    def complete(self, component: str, payload: dict[str, object],
                 schema: type[object]) -> tuple[dict[str, object], int, int]:
        return {"changes": [{"path": "src/shop/users.py", "content": "example"}],
                "rationale": "test"}, 3, 5


def test_final_prompt_documents_are_self_contained() -> None:
    first = (ROOT / "docs/prompts/01_environment_fixture.md").read_text()
    second = (ROOT / "docs/prompts/02_happy_path_e2e.md").read_text()
    assert first.startswith("Prompt: 01_environment_fixture\nVersion: v1\n")
    assert "pydantic==1.10.26" in first
    assert "# Acceptance Criteria" in first
    assert second.startswith("Prompt: 02_happy_path_e2e\nVersion: v1.1\n")
    for requirement in (
        "candidate checkpoint", "last_stable_snapshot", "configured verification Python",
        "rg", "AST", "dependency/config parsing", "test discovery",
        "import/reference relationships", "snippet-level", "max_files", "max_snippets",
        "max_context_tokens", "ranking reason", "assertions", "main/default-branch commit",
        "controlled-model end-to-end test", "READY_FOR_PR", "DEFERRED / optional",
    ):
        assert requirement in second


def test_new_version_and_legacy_run_loading(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "runs.db")
    run = RunRecord(run_id="new", request=MigrationRequest(repository="example"),
                    current_state=State.RECEIVED, repository_identifiers={},
                    started_at="2026-01-01T00:00:00Z")
    assert run.prompt_version == "v1.1"
    store.save(run)
    assert store.load(run.run_id).prompt_version == "v1.1"
    old_data = json.loads(run.json())
    old_data["run_id"] = "legacy"
    old_data["prompt_version"] = "v1"
    legacy = RunRecord.parse_obj(old_data)
    store.save(legacy)
    assert store.load("legacy").prompt_version == "v1"
    client = ModelClient(ProposalBackend(), store)
    client.call(run.run_id, "Patch Generator", {}, PatchProposal)
    assert store.model_calls(run.run_id)[0].prompt_version == "v1.1"
