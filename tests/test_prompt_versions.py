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


def test_prompt3_contract_is_self_contained() -> None:
    third = (ROOT / "docs/prompts/03_failure_repair_path.md").read_text()
    assert third.startswith("Prompt: 03_failure_repair_path\nVersion: v1\n")
    for requirement in ("Maximum 3 Total Attempts", "ANALYZING_FAILURE",
                        "GATHERING_ADDITIONAL_CONTEXT", "NEEDS_HUMAN_REVIEW",
                        "FailureAnalyzer", "ReviewDecision", "candidate checkpoint",
                        "last verified stable snapshot", "rollback", "max_context_tokens",
                        "Live Sol execution remains deferred"):
        assert requirement in third


def test_new_version_and_legacy_run_loading(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "runs.db")
    run = RunRecord(run_id="new", request=MigrationRequest(repository="example", migration_goal="Upgrade Pydantic v1 to Pydantic v2"),
                    current_state=State.RECEIVED, repository_identifiers={}, use_case=1, migration_family="pydantic",
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


def test_legacy_pydantic_analysis_loads_into_generic_schema(tmp_path: Path) -> None:
    import sqlite3

    from patchpilot.workflow.repository import analyze

    store = RunStore(tmp_path / "legacy.db")
    fixture = Path(__file__).parents[1] / "fixtures/pydantic_v1_app"
    run = RunRecord(
        run_id="old-analysis",
        request=MigrationRequest(repository=str(fixture),
                                 migration_goal="Upgrade Pydantic v1 to Pydantic v2"),
        current_state=State.ANALYZING_REPO,
        repository_identifiers={}, use_case=1, migration_family="pydantic",
        analysis=analyze(fixture), started_at="2026-01-01T00:00:00Z",
    )
    data = json.loads(run.json())
    data.pop("use_case")
    data.pop("migration_family")
    old_analysis = data["analysis"]
    old_analysis["pydantic_version"] = old_analysis["dependency_version"]
    old_analysis["v1_usages"] = old_analysis.pop("migration_api_usages")
    for key in ("source_version", "target_version", "shared_base_symbols"):
        old_analysis.pop(key)
    with sqlite3.connect(store.path) as db:
        db.execute("INSERT INTO runs VALUES (?, ?)", (run.run_id, json.dumps(data)))
    loaded = store.load(run.run_id)
    assert loaded.migration_family == "pydantic" and loaded.use_case == 1
    assert loaded.analysis is not None
    assert loaded.analysis.source_version == "1.10.26"
    assert loaded.analysis.migration_api_usages
