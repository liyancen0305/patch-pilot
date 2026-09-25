"""Synthetic observations test arithmetic and gates, never provider quality."""

import copy
import json
from pathlib import Path

import pytest

from patchpilot.evaluation.core import (
    COMPONENTS,
    FIXTURES,
    assignment,
    compare,
    final_assignment,
    fingerprint,
    percentile95,
    require_live,
    summarize,
)
from patchpilot.evaluation.pricing import call_cost
from patchpilot.evaluation.runner import RoutedBackend, measure, validate_config
from patchpilot.workflow.benchmarks import FAMILIES
from patchpilot.workflow.model import ModelClient
from patchpilot.workflow.schema import PatchProposal
from patchpilot.workflow.store import RunStore

ROOT = Path(__file__).resolve().parents[1]
CONFIG = json.loads((ROOT / "config/model_evaluation.json").read_text())


def evidence(component=None):
    """Synthetic dict for decision-unit tests only; never written as live evidence."""
    config = copy.deepcopy(CONFIG)
    config["minimum_component_calls"] = 1
    selected = assignment(component)
    rows = []
    for repetition in range(config["repetitions"]):
        for family in FIXTURES:
            calls = [
                {
                    "source": "live",
                    "component": name,
                    "model": config["models"][selected[name]],
                    "latency_seconds": 1.1 if name == component else 1,
                    "cost_usd": 0.1 if name == component else 1,
                }
                for name in COMPONENTS
            ]
            rows.append(
                {
                    "migration_family": family,
                    "repetition": repetition,
                    "success": True,
                    "first_attempt_success": True,
                    "repair_success": True,
                    "human_escalation": False,
                    "regressions_introduced": False,
                    "unnecessary_modification": False,
                    "reviewer_correct": True,
                    "safety_preserved": True,
                    "end_to_end_seconds": 10,
                    "cost_usd": sum(c["cost_usd"] for c in calls),
                    "calls": calls,
                }
            )
    return {
        "mode": "live",
        "status": "MEASURED",
        "config": config,
        "fingerprint": {"fixture": "hash"},
        "environments": {},
        "assignment": selected,
        "rows": rows,
    }


def test_frozen_benchmark_and_architecture():
    assert tuple(f.name for f in FAMILIES) == tuple(FIXTURES)
    lock = json.loads((ROOT / "config/evaluation_freeze.json").read_text())
    actual = fingerprint(ROOT)
    assert all(actual[path] == digest for path, digest in lock.items())
    source = (ROOT / "src/patchpilot/workflow/runner.py").read_text()
    assert "evaluation" not in source and "Terra" not in source


@pytest.mark.parametrize("component", COMPONENTS)
def test_exactly_one_substitution(component):
    selected = assignment(component)
    assert [key for key in selected if selected[key] != assignment()[key]] == [
        component
    ]
    assert selected[component] == "Terra"


def test_config_and_unknown_component():
    validate_config(CONFIG)
    with pytest.raises(ValueError):
        assignment("Orchestrator")
    config = copy.deepcopy(CONFIG)
    del config["verification_python"]["celery"]
    with pytest.raises(ValueError):
        validate_config(config)


def test_p95_and_summary():
    assert percentile95([]) is None
    assert percentile95([3]) == 3
    assert percentile95(list(range(1, 21))) == 19
    assert percentile95(list(range(100, 0, -1))) == 95
    summary = summarize(evidence()["rows"])
    assert summary["quality"]["success_rate"] == 1
    assert summary["total_cost_usd"] == 90
    assert summary["average_cost_usd"] == 6
    assert summary["components"]["Migration Planner/gpt-5.6-sol"]["p95_seconds"] == 1


def test_central_pricing_unknown_and_test_double():
    pricing = {
        "version": "synthetic",
        "usd_per_million_tokens": {"model": {"input": 2, "output": 8}},
    }
    assert call_cost(pricing, "model", 100, 200, live=True) == 0.0018
    assert call_cost(pricing, "model", 100, 200, live=False) is None
    assert call_cost(pricing, "model", None, 200, live=True) is None
    assert call_cost(pricing, "unknown", 100, 200, live=True) is None
    assert all(
        call_cost(CONFIG["pricing"], model, 1, 1, live=True) is None
        for model in CONFIG["models"].values()
    )


class Fake:
    model = "test-double"

    def complete(self, component, payload, schema):
        return (
            {
                "changes": [{"path": "example.py", "content": "x = 1"}],
                "rationale": "test",
            },
            7,
            9,
        )


def test_config_driven_route_and_test_double_provenance(tmp_path):
    selected = assignment("Patch Generator")
    backend = RoutedBackend(
        selected, CONFIG, tmp_path / "calls.json", test_backend=Fake()
    )
    store = RunStore(tmp_path / "runs.db")
    ModelClient(backend, store).call("test", "Patch Generator", {}, PatchProposal)
    call = json.loads((tmp_path / "calls.json").read_text())["calls"][0]
    assert call["assigned_model"] == CONFIG["models"]["Terra"]
    assert call["source"] == "test_double"
    assert call["input_tokens"] is None and call["cost_usd"] is None
    assert store.model_calls("test")[0].estimated_cost_usd is None
    result = evidence("Patch Generator")
    result["rows"][0]["calls"] = [call]
    with pytest.raises(ValueError, match="Test-double"):
        require_live(result)


def test_real_adapter_only_changes_model_identifier(tmp_path, monkeypatch):
    import io
    import urllib.request

    requests = []

    def provider(request, timeout):
        requests.append(json.loads(request.data))
        return io.BytesIO(
            json.dumps(
                {
                    "status": "completed",
                    "output": [
                        {
                            "content": [
                                {
                                    "type": "output_text",
                                    "text": json.dumps(
                                        {
                                            "changes": [
                                                {
                                                    "path": "example.py",
                                                    "content": "x = 1",
                                                }
                                            ],
                                            "rationale": "test",
                                        }
                                    ),
                                }
                            ]
                        }
                    ],
                    "usage": {"input_tokens": 7, "output_tokens": 9},
                }
            ).encode()
        )

    monkeypatch.setenv("OPENAI_API_KEY", "fake-for-unit-test")
    monkeypatch.setattr(urllib.request, "urlopen", provider)
    for selected in (assignment(), assignment("Patch Generator")):
        backend = RoutedBackend(selected, CONFIG, tmp_path / "calls.json")
        backend.complete("Patch Generator", {"example": "identical"}, PatchProposal)
    assert requests[0].pop("model") == CONFIG["models"]["Sol"]
    assert requests[1].pop("model") == CONFIG["models"]["Terra"]
    assert requests[0] == requests[1]


def test_baseline_and_selection_gates(tmp_path):
    with pytest.raises(ValueError, match="baseline first"):
        measure(
            ROOT,
            tmp_path,
            "Patch Generator",
            assignment("Patch Generator"),
            CONFIG,
            {},
            {},
        )
    baseline = evidence()
    candidate = evidence("Patch Generator")
    assert compare(baseline, candidate, "Patch Generator")["decision"] == "USE_TERRA"
    candidate["rows"][0]["success"] = False
    assert compare(baseline, candidate, "Patch Generator")["decision"] == "KEEP_SOL"
    with pytest.raises(ValueError):
        final_assignment(baseline, {})
    baseline["mode"] = "test_double"
    with pytest.raises(ValueError):
        require_live(baseline)


def test_latency_tradeoff_missing_labels_and_input_drift():
    baseline, candidate = evidence(), evidence("Change Reviewer")
    for row in candidate["rows"]:
        for call in row["calls"]:
            if call["component"] == "Change Reviewer":
                call["latency_seconds"] = 1.21
    result = compare(baseline, candidate, "Change Reviewer")
    assert result["decision"] == "INCONCLUSIVE" and "justification" in result["reason"]
    candidate = evidence("Change Reviewer")
    for row in candidate["rows"]:
        row["reviewer_correct"] = None
    assert compare(baseline, candidate, "Change Reviewer")["decision"] == "INCONCLUSIVE"
    candidate["fingerprint"] = {}
    with pytest.raises(ValueError, match="fingerprint"):
        compare(baseline, candidate, "Change Reviewer")


def test_final_assignment_and_optimized_configuration_gate(tmp_path):
    baseline = evidence()
    candidates = {name: evidence(name) for name in COMPONENTS}
    selected = final_assignment(baseline, candidates)
    assert selected == dict.fromkeys(COMPONENTS, "Terra")
    (tmp_path / "sol_baseline.json").write_text(json.dumps(baseline))
    with pytest.raises(ValueError, match="evidence-selected"):
        measure(
            ROOT,
            tmp_path,
            "optimized_results",
            assignment(),
            baseline["config"],
            baseline["fingerprint"],
            baseline["environments"],
            baseline,
            candidates,
        )


def test_failed_calls_have_unknown_cost_and_durable_telemetry(tmp_path):
    class Broken:
        def complete(self, *args):
            raise RuntimeError("failed")

    backend = RoutedBackend(
        assignment(), CONFIG, tmp_path / "calls.json", test_backend=Broken()
    )
    with pytest.raises(RuntimeError):
        backend.complete("Migration Planner", {}, PatchProposal)
    call = json.loads((tmp_path / "calls.json").read_text())["calls"][0]
    assert call["error"] == "RuntimeError" and call["cost_usd"] is None


def test_incomplete_benchmark_cannot_support_selection():
    result = evidence()
    result["rows"].pop()
    with pytest.raises(ValueError, match="Incomplete"):
        require_live(result)


def test_quality_annotations_require_evidence_and_preserve_observations(tmp_path):
    from patchpilot.evaluation.runner import annotate

    result = evidence()
    for index, row in enumerate(result["rows"]):
        row["run_id"] = str(index)
    label = {
        "adjudicator": "unit-test",
        "evidence_file": str(tmp_path / "review.txt"),
        "labels": {
            "regressions_introduced": False,
            "unnecessary_modification": False,
            "reviewer_correct": True,
            "safety_preserved": True,
        },
    }
    with pytest.raises(ValueError, match="existing evidence"):
        annotate(result, {"0": label})
    (tmp_path / "review.txt").write_text("Synthetic adjudication for unit testing only")
    updated = annotate(result, {"0": label})
    assert updated["rows"][0]["quality_annotation"]["sha256"]
    assert updated["rows"][0]["calls"] == result["rows"][0]["calls"]


def test_partial_quality_labels_and_wrong_call_model_cannot_select():
    baseline, candidate = evidence(), evidence("Patch Generator")
    candidate["rows"][0]["unnecessary_modification"] = None
    assert compare(baseline, candidate, "Patch Generator")["decision"] == "INCONCLUSIVE"
    candidate["rows"][0]["calls"][0]["model"] = "unconfigured-model"
    with pytest.raises(ValueError, match="telemetry"):
        require_live(candidate)


def test_missing_provider_usage_is_not_zero_cost(tmp_path, monkeypatch):
    import io
    import urllib.request

    monkeypatch.setenv("OPENAI_API_KEY", "unit-test")
    monkeypatch.setattr(
        urllib.request,
        "urlopen",
        lambda *args, **kwargs: io.BytesIO(
            json.dumps({"status": "completed", "output": []}).encode()
        ),
    )
    backend = RoutedBackend(assignment(), CONFIG, tmp_path / "calls.json")
    with pytest.raises(ValueError, match="token usage"):
        backend.complete("Patch Generator", {}, PatchProposal)
    assert backend.calls[0]["input_tokens"] is None
    assert backend.calls[0]["cost_usd"] is None


def test_router_preserves_real_repair_workflow_states(tmp_path):
    from test_prompt3_repair import RepairModel, _run, _states

    histories = []
    for index, selected in enumerate((assignment(), assignment("Repair Generator"))):
        destination = tmp_path / str(index)
        backend = RoutedBackend(
            selected, CONFIG, destination / "calls.json", test_backend=RepairModel()
        )
        run, store = _run(destination, backend)
        histories.append(_states(store, run.run_id))
        assert run.current_state.value == "READY_FOR_PR"
        assert run.attempt_number == 2
        assert all(
            call["source"] == "test_double" and call["cost_usd"] is None
            for call in backend.calls
        )
    assert histories[0] == histories[1]


def test_optimized_runner_uses_selected_configuration_for_all_five_cases(
    tmp_path, monkeypatch
):
    from types import SimpleNamespace

    import patchpilot.evaluation.runner as module

    baseline = evidence()
    candidates = {name: evidence(name) for name in COMPONENTS}
    selected = final_assignment(baseline, candidates)
    (tmp_path / "sol_baseline.json").write_text(json.dumps(baseline))
    seen = []

    class StubWorkflow:
        def __init__(self, store, client, verifier, **kwargs):
            seen.append(client.backend.selected)

        def run(self, *args, **kwargs):
            return SimpleNamespace(
                current_state=SimpleNamespace(value="FAILED_SYSTEM"),
                run_id=str(len(seen)),
                attempt_number=1,
                review_history=[],
                context_expansions=[],
                patch=None,
            )

    monkeypatch.setattr(module, "Workflow", StubWorkflow)
    monkeypatch.setattr(module, "fingerprint", lambda root: baseline["fingerprint"])
    monkeypatch.setattr(
        module, "environment_snapshot", lambda config: baseline["environments"]
    )
    result = measure(
        ROOT,
        tmp_path,
        "optimized_results",
        selected,
        baseline["config"],
        baseline["fingerprint"],
        baseline["environments"],
        baseline,
        candidates,
    )
    assert len(seen) == 5 * baseline["config"]["repetitions"]
    assert all(item == selected for item in seen)
    assert {row["migration_family"] for row in result["rows"]} == set(FIXTURES)
    # Exercising the runner without real calls must never produce measured evidence.
    assert result["status"] == "BLOCKED / NOT YET MEASURED"
    with pytest.raises(ValueError):
        require_live(result)


def test_tradeoff_report_uses_decision_evidence(tmp_path):
    from patchpilot.evaluation.report import write_tradeoffs

    decision = compare(evidence(), evidence("Patch Generator"), "Patch Generator")
    write_tradeoffs(
        tmp_path, [decision], "Synthetic unit test only", {"Patch Generator": "Terra"}
    )
    report = (tmp_path / "model_tradeoffs.md").read_text()
    assert "Synthetic unit test only" in report
    assert decision["reason"] in report and "USE_TERRA" in report


def test_measure_never_overwrites_existing_live_evidence(tmp_path):
    path = tmp_path / "sol_baseline.json"
    original = json.dumps(evidence())
    path.write_text(original)
    with pytest.raises(ValueError, match="immutable"):
        measure(ROOT, tmp_path, "sol_baseline", assignment(), CONFIG, {}, {})
    assert path.read_text() == original
