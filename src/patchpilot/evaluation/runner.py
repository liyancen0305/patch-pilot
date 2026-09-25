"""Baseline-first experiments around the unchanged Workflow and model prompts.

Evaluation journals are authoritative for mixed-model provenance. Legacy workflow
model_type and estimated costs are not used to make model-selection decisions.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import time
from pathlib import Path
from typing import Any

from patchpilot.workflow import RunStore, VerificationRunner, Workflow
from patchpilot.workflow.benchmarks import FAMILIES
from patchpilot.workflow.model import ModelClient, SolBackend
from patchpilot.workflow.schema import MigrationRequest

from .core import (
    COMPONENTS,
    FIXTURES,
    PROMPT,
    assignment,
    check_freeze,
    compare,
    final_assignment,
    fingerprint,
    require_live,
    summarize,
    total_cost,
    write_json,
)
from .pricing import call_cost
from .report import write_tradeoffs


class RoutedBackend:
    """Change only the API model identifier; reuse existing prompts and schemas."""

    def __init__(
        self,
        selected: dict[str, str],
        config: dict[str, Any],
        journal: Path,
        *,
        test_backend: Any = None,
    ) -> None:
        if set(selected) != set(COMPONENTS) or set(selected.values()) - {
            "Sol",
            "Terra",
        }:
            raise ValueError("Exactly six valid model assignments required")
        self.selected, self.config, self.journal = selected, config, journal
        self.test_backend = test_backend
        self.live = test_backend is None
        self.model = "evaluation-router"
        self.calls: list[dict[str, Any]] = []

    def complete(self, component: str, payload: dict[str, Any], schema: Any) -> Any:
        label = self.selected[component]
        self.model = self.config["models"][label]
        backend = self.test_backend if self.test_backend is not None else SolBackend()
        live = self.test_backend is None
        if live:
            backend.model = self.model
        started = time.perf_counter()
        input_tokens = output_tokens = None
        error = None
        try:
            output, input_tokens, output_tokens = backend.complete(
                component, payload, schema
            )
            return output, input_tokens, output_tokens
        except Exception as exc:
            # Do not persist API response bodies or credentials from exception messages.
            error = type(exc).__name__
            raise
        finally:
            self.calls.append(
                {
                    "source": "live" if live else "test_double",
                    "component": component,
                    "model": self.model
                    if live
                    else getattr(backend, "model", "test_double"),
                    "assigned_model": self.model,
                    "input_tokens": input_tokens if live else None,
                    "output_tokens": output_tokens if live else None,
                    "latency_seconds": time.perf_counter() - started,
                    "cost_usd": call_cost(
                        self.config["pricing"],
                        self.model,
                        input_tokens,
                        output_tokens,
                        live=live,
                    ),
                    "pricing_version": self.config["pricing"]["version"],
                    "error": error,
                }
            )
            write_json(
                self.journal,
                {
                    "prompt": PROMPT,
                    "config": self.config,
                    "assignment": self.selected,
                    "calls": self.calls,
                },
            )


def environment_snapshot(config: dict[str, Any]) -> dict[str, Any]:
    snapshot = {}
    for name, executable in config["verification_python"].items():
        result = subprocess.run(
            [
                executable,
                "-c",
                (
                    "import importlib.metadata as m; "
                    "print('\\n'.join(sorted(d.metadata['Name']+'=='+d.version for d in m.distributions())))"
                ),
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        snapshot[name] = {
            "python": executable,
            "packages": sorted(result.stdout.splitlines()),
            "version": subprocess.check_output(
                [executable, "--version"], text=True
            ).strip(),
        }
    return snapshot


def preflight(config: dict[str, Any]) -> list[str]:
    reasons = []
    if not os.environ.get("OPENAI_API_KEY"):
        reasons.append("OPENAI_API_KEY is unavailable")
    for label, model in config["models"].items():
        if call_cost(config["pricing"], model, 1, 1, live=True) is None:
            reasons.append(
                f"{label} pricing is unconfigured; verify provider rates/version"
            )
    for name, executable in config["verification_python"].items():
        if not Path(executable).is_file():
            reasons.append(f"{name} verification environment missing: {executable}")
    return reasons


def validate_config(config: dict[str, Any]) -> None:
    if config["prompt"] != PROMPT or set(config["models"]) != {"Sol", "Terra"}:
        raise ValueError("Invalid prompt or model configuration")
    if set(config["verification_python"]) != set(FIXTURES):
        raise ValueError("The five-family benchmark is frozen")
    if not isinstance(config["repetitions"], int) or config["repetitions"] < 1:
        raise ValueError("Repetitions must be a positive integer")
    if config["models"]["Sol"] == config["models"]["Terra"]:
        raise ValueError("Sol and Terra must resolve to different provider models")
    for key in (
        "quality_tolerance",
        "minimum_cost_savings_fraction",
        "maximum_p95_slowdown_fraction",
    ):
        if not 0 <= config[key] <= 1:
            raise ValueError(f"Invalid {key}")
    if config["minimum_component_calls"] < 1:
        raise ValueError("A component must be exercised to be selected")


def measure(
    root: Path,
    directory: Path,
    name: str,
    selected: dict[str, str],
    config: dict[str, Any],
    frozen: dict[str, str],
    environments: dict[str, Any],
    baseline: dict[str, Any] | None = None,
    candidates: dict[str, Any] | None = None,
) -> dict[str, Any]:
    path = directory / (name.replace(" ", "_") + ".json")
    if path.exists() and json.loads(path.read_text()).get("mode") == "live":
        raise ValueError(
            "Existing live experiment is immutable; use a fresh output directory"
        )
    if name == "sol_baseline":
        if selected != assignment():
            raise ValueError("Sol baseline must use Sol for every component")
    else:
        if baseline is None:
            raise ValueError("Record the complete live Sol baseline first")
        require_live(baseline)
        for key, value in (
            ("config", config),
            ("fingerprint", frozen),
            ("environments", environments),
        ):
            if baseline[key] != value:
                raise ValueError(f"Substitution changed {key} before execution")
        persisted = json.loads((directory / "sol_baseline.json").read_text())
        if persisted != baseline:
            raise ValueError("Baseline must already be durably recorded")
        if name == "optimized_results":
            if selected != final_assignment(baseline, candidates or {}):
                raise ValueError(
                    "Optimized run must use the evidence-selected configuration"
                )
        elif name not in COMPONENTS or selected != assignment(name):
            raise ValueError("Only one component can change during substitution")
    if fingerprint(root) != frozen or environment_snapshot(config) != environments:
        raise ValueError("Frozen evaluation inputs changed")
    result: dict[str, Any] = {
        "prompt": PROMPT,
        "config": config,
        "assignment": selected,
        "fingerprint": frozen,
        "environments": environments,
        "mode": "live",
        "status": "RUNNING",
        "rows": [],
        "experiment": name,
        "started_at_unix": time.time(),
        "workflow_prompt": {"name": "05_guardrails_failures", "version": "v1"},
        "limitations": [
            "Unexercised components are inconclusive",
            "Quality annotations require independent evidence",
            "Small benchmark; empirical p95 is not a population guarantee",
        ],
    }
    write_json(path, result)
    for repetition in range(config["repetitions"]):
        for family in FAMILIES:
            destination = (
                directory
                / "runs"
                / name.replace(" ", "_")
                / str(repetition)
                / family.name
            )
            destination.mkdir(parents=True, exist_ok=False)
            store = RunStore(destination / "runs.db")
            backend = RoutedBackend(selected, config, destination / "calls.json")
            started = time.perf_counter()
            fixture = root / "fixtures" / FIXTURES[family.name]
            try:
                run = Workflow(
                    store,
                    ModelClient(backend, store),
                    VerificationRunner(
                        Path(config["verification_python"][family.name])
                    ),
                    repair_enabled=True,
                    benchmark_mode=True,
                ).run(
                    fixture,
                    destination,
                    approval="APPROVE",
                    request=MigrationRequest(
                        repository=str(fixture), migration_goal=family.goal
                    ),
                )
            except Exception as exc:
                result.update(status="INTERRUPTED", error=type(exc).__name__)
                write_json(path, result)
                raise
            success = run.current_state.value == "READY_FOR_PR"
            row = {
                "migration_family": family.name,
                "repetition": repetition,
                "run_id": run.run_id,
                "final_state": run.current_state.value,
                "success": success,
                "first_attempt_success": success and run.attempt_number == 1,
                "total_attempts": run.attempt_number,
                "repair_success": success if run.attempt_number > 1 else None,
                "reviewer_usage": len(run.review_history),
                "context_expansions": len(run.context_expansions),
                "files_changed": run.patch.changed_files if run.patch else [],
                "human_escalation": run.current_state.value == "NEEDS_HUMAN_REVIEW",
                "regressions_introduced": None,
                "unnecessary_modification": None,
                "reviewer_correct": None,
                "safety_preserved": None,
                "quality_annotation": "NOT YET MEASURED; verification success alone is not ground truth",
                "calls": backend.calls,
                "model_calls": len(backend.calls),
                "input_tokens": token_total(backend.calls, "input_tokens"),
                "output_tokens": token_total(backend.calls, "output_tokens"),
                "cost_usd": total_cost(backend.calls),
                "end_to_end_seconds": time.perf_counter() - started,
                "workflow_artifacts": str(destination),
            }
            result["rows"].append(row)
            write_json(path, result)
            if fingerprint(root) != frozen:
                result["status"] = "INVALID_INPUT_DRIFT"
                write_json(path, result)
                raise ValueError("Frozen files changed during experiment")
    if environment_snapshot(config) != environments:
        result["status"] = "INVALID_ENVIRONMENT_DRIFT"
    elif not any(
        call["error"] is None and call["input_tokens"] is not None
        for row in result["rows"]
        for call in row["calls"]
    ):
        result["status"] = "BLOCKED / NOT YET MEASURED"
        result["reasons"] = [
            "No successful live provider response; inspect call errors and environments"
        ]
    else:
        result["status"] = "MEASURED"
    result["summary"] = summarize(result["rows"])
    result["ended_at_unix"] = time.time()
    write_json(path, result)
    return result


def token_total(calls: list[dict[str, Any]], key: str) -> int | None:
    return (
        sum(c[key] for c in calls)
        if calls and all(c[key] is not None for c in calls)
        else None
    )


def annotate(result: dict[str, Any], annotations: dict[str, Any]) -> dict[str, Any]:
    """Attach human-adjudicated labels with content-addressed evidence; never infer them."""
    require_live(result)
    fields = {
        "regressions_introduced",
        "unnecessary_modification",
        "reviewer_correct",
        "safety_preserved",
    }
    for row in result["rows"]:
        label = annotations.get(row["run_id"])
        if label is None:
            continue
        if set(label["labels"]) != fields or any(
            value is not None and not isinstance(value, bool)
            for value in label["labels"].values()
        ):
            raise ValueError(
                "Quality labels must provide all four fields as boolean or null"
            )
        evidence_path = Path(label["evidence_file"])
        if not label.get("adjudicator") or not evidence_path.is_file():
            raise ValueError("An adjudicator and existing evidence file are required")
        row.update(label["labels"])
        row["quality_annotation"] = {
            "adjudicator": label["adjudicator"],
            "evidence_file": str(evidence_path),
            "sha256": hashlib.sha256(evidence_path.read_bytes()).hexdigest(),
        }
    result["summary"] = summarize(result["rows"])
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument(
        "--config", type=Path, default=Path("config/model_evaluation.json")
    )
    parser.add_argument("--output", type=Path, default=Path("artifacts/evaluation"))
    parser.add_argument(
        "--live",
        action="store_true",
        help="Execute real provider calls after preflight",
    )
    parser.add_argument(
        "--finalize",
        action="store_true",
        help="Adjudicate existing live experiments and rerun selected assignment",
    )
    parser.add_argument(
        "--annotations",
        type=Path,
        help="JSON keyed by run_id with labels, adjudicator, evidence_file",
    )
    args = parser.parse_args()
    config = json.loads(args.config.read_text())
    validate_config(config)
    frozen = fingerprint(args.root)
    check_freeze(args.root, frozen)
    reasons = preflight(config)
    if not args.live:
        reasons.append(
            "Live execution not requested (pass --live after configuring access/pricing)"
        )
    common = {
        "prompt": PROMPT,
        "config": config,
        "fingerprint": frozen,
        "status": "BLOCKED / NOT YET MEASURED",
        "mode": "not_measured",
        "reasons": reasons,
    }
    if reasons:
        # Never overwrite existing measured evidence with a preflight report.
        if (args.output / "sol_baseline.json").exists():
            previous = json.loads((args.output / "sol_baseline.json").read_text())
            if previous.get("mode") == "live":
                raise ValueError(
                    "Use a new output directory; existing live evidence is immutable"
                )
        write_json(
            args.output / "sol_baseline.json",
            {**common, "assignment": assignment(), "rows": []},
        )
        write_json(
            args.output / "component_comparisons.json",
            {
                **common,
                "comparisons": [
                    {
                        "component": c,
                        "assignment": assignment(c),
                        "decision": "INCONCLUSIVE",
                        "reason": "Live Sol baseline must be recorded first",
                        "quality_difference": None,
                        "average_cost_difference_usd": None,
                        "p95_latency_difference_seconds": None,
                    }
                    for c in COMPONENTS
                ],
            },
        )
        write_json(
            args.output / "optimized_results.json",
            {
                **common,
                "assignment": None,
                "rows": [],
                "reason": "Final assignment and optimized rerun require measured evidence",
            },
        )
        print("BLOCKED / NOT YET MEASURED: " + "; ".join(reasons))
        return
    if args.finalize:
        if args.annotations is None:
            raise ValueError("Finalization requires independent quality annotations")
        annotations = json.loads(args.annotations.read_text())
        results = {}
        for name in ("sol_baseline", *COMPONENTS):
            path = args.output / (name.replace(" ", "_") + ".json")
            result = json.loads(path.read_text())
            if result["config"] != config or result["fingerprint"] != frozen:
                raise ValueError("Finalization inputs differ from recorded experiments")
            if not path.with_suffix(".unannotated.json").exists():
                write_json(path.with_suffix(".unannotated.json"), result)
            results[name] = annotate(result, annotations)
            write_json(path, results[name])
        baseline = results.pop("sol_baseline")
        comparisons = [compare(baseline, results[c], c) for c in COMPONENTS]
        write_json(
            args.output / "component_comparisons.json",
            {"prompt": PROMPT, "config": config, "comparisons": comparisons},
        )
        write_tradeoffs(args.output, comparisons, "Awaiting conclusive selection")
        selected = final_assignment(baseline, results)
        write_tradeoffs(
            args.output, comparisons, "Selected; optimized rerun pending", selected
        )
        optimized = measure(
            args.root,
            args.output,
            "optimized_results",
            selected,
            config,
            frozen,
            environment_snapshot(config),
            baseline,
            results,
        )
        write_tradeoffs(
            args.output,
            comparisons,
            f"Optimized benchmark {optimized['status']}; independent quality review pending",
            selected,
        )
        return
    if (args.output / "sol_baseline.json").exists():
        raise ValueError(
            "Use a fresh output directory to preserve prior evaluation evidence"
        )
    environments = environment_snapshot(config)
    baseline = measure(
        args.root,
        args.output,
        "sol_baseline",
        assignment(),
        config,
        frozen,
        environments,
    )
    candidates, comparisons = {}, []
    for component in COMPONENTS:
        candidates[component] = measure(
            args.root,
            args.output,
            component,
            assignment(component),
            config,
            frozen,
            environments,
            baseline,
        )
        comparisons.append(compare(baseline, candidates[component], component))
        write_json(
            args.output / "component_comparisons.json",
            {"prompt": PROMPT, "config": config, "comparisons": comparisons},
        )
    write_tradeoffs(args.output, comparisons, "Awaiting conclusive selection")
    try:
        selected = final_assignment(baseline, candidates)
    except ValueError as exc:
        write_json(
            args.output / "optimized_results.json",
            {**common, "reasons": [str(exc)], "assignment": None, "rows": []},
        )
        print(str(exc))
        return
    write_tradeoffs(
        args.output, comparisons, "Selected; optimized rerun pending", selected
    )
    optimized = measure(
        args.root,
        args.output,
        "optimized_results",
        selected,
        config,
        frozen,
        environments,
        baseline,
        candidates,
    )
    write_tradeoffs(
        args.output,
        comparisons,
        f"Optimized benchmark {optimized['status']}; independent quality review pending",
        selected,
    )


if __name__ == "__main__":
    main()
