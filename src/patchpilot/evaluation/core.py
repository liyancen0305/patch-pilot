"""Frozen evaluation inputs, measurements, and conservative selection rules."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from statistics import mean
from typing import Any

COMPONENTS = (
    "Migration Planner",
    "Patch Generator",
    "Failure Analyzer",
    "Repair Generator",
    "Change Reviewer",
    "CapabilityClassifier",
)
FIXTURES = {
    "pydantic": "pydantic_v1_app",
    "sqlalchemy": "sqlalchemy_14",
    "httpx": "httpx_027",
    "openai": "openai_028",
    "celery": "celery_4",
}
PROMPT = {"name": "06_model_optimization_eval", "version": "v1"}
QUALITY = {
    "success_rate": 1,
    "first_pass_rate": 1,
    "repair_success_rate": 1,
    "unnecessary_modification_rate": -1,
    "regression_rate": -1,
    "human_escalation_rate": -1,
    "reviewer_correctness": 1,
    "safety_preservation_rate": 1,
}


def assignment(component: str | None = None) -> dict[str, str]:
    if component is not None and component not in COMPONENTS:
        raise ValueError("Only LLM-backed components may be substituted")
    return {name: "Terra" if name == component else "Sol" for name in COMPONENTS}


def percentile95(values: list[float]) -> float | None:
    """Nearest-rank empirical p95: sorted[ceil(.95*n)-1], no interpolation."""
    return sorted(values)[math.ceil(0.95 * len(values)) - 1] if values else None


def latency(values: list[float]) -> dict[str, Any]:
    return {
        "count": len(values),
        "average_seconds": mean(values) if values else None,
        "p95_seconds": percentile95(values),
    }


def fingerprint(root: Path) -> dict[str, str]:
    # Include hidden fixture configuration; exclude only generated caches/Git metadata.
    paths = list((root / "fixtures").rglob("*"))
    for directory in ("src/patchpilot", "docs/prompts", "benchmark_solutions", "tests"):
        paths.extend((root / directory).rglob("*"))
    paths.extend((root / "scripts").glob("*.py"))
    paths.extend((root / "scripts").glob("*.sh"))
    paths.append(root / "pyproject.toml")
    return {
        str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(set(paths))
        if p.is_file()
        and not any(
            part
            in {".git", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache"}
            for part in p.parts
        )
        and p.suffix != ".pyc"
    }


def check_freeze(root: Path, actual: dict[str, str]) -> None:
    lock = json.loads((root / "config/evaluation_freeze.json").read_text())
    prefixes = (
        "fixtures/",
        "src/patchpilot/workflow/",
        "src/patchpilot/sandbox/",
        "src/patchpilot/tools/",
        "src/patchpilot/storage/",
    )
    selected = {
        path: digest
        for path, digest in actual.items()
        if path.startswith(prefixes) and path != "src/patchpilot/workflow/model.py"
    }
    if selected != lock:
        raise ValueError("Frozen benchmark or deterministic architecture changed")


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(data, indent=2, sort_keys=True, allow_nan=False) + "\n"
    )
    temporary.replace(path)


def rate(rows: list[dict[str, Any]], field: str) -> float | None:
    values = [row[field] for row in rows if row.get(field) is not None]
    return mean(values) if values else None


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    calls = [call for row in rows for call in row["calls"]]
    groups = sorted({(call["component"], call["model"]) for call in calls})
    costs = [row["cost_usd"] for row in rows]
    return {
        "quality": {
            "success_rate": rate(rows, "success"),
            "first_pass_rate": rate(rows, "first_attempt_success"),
            "repair_success_rate": rate(rows, "repair_success"),
            "human_escalation_rate": rate(rows, "human_escalation"),
            **{
                metric: rate(rows, field)
                for metric, field in (
                    ("regression_rate", "regressions_introduced"),
                    ("unnecessary_modification_rate", "unnecessary_modification"),
                    ("reviewer_correctness", "reviewer_correct"),
                    ("safety_preservation_rate", "safety_preserved"),
                )
            },
        },
        "quality_denominators": {
            field: sum(row.get(field) is not None for row in rows)
            for field in (
                "success",
                "first_attempt_success",
                "repair_success",
                "human_escalation",
                "regressions_introduced",
                "unnecessary_modification",
                "reviewer_correct",
                "safety_preserved",
            )
        },
        "quality_label_counts": {
            field: sum(row.get(field) is not None for row in rows)
            for field in (
                "regressions_introduced",
                "unnecessary_modification",
                "reviewer_correct",
                "safety_preserved",
            )
        },
        "total_cost_usd": sum(costs)
        if costs and all(c is not None for c in costs)
        else None,
        "average_cost_usd": mean(costs)
        if costs and all(c is not None for c in costs)
        else None,
        "end_to_end_latency": latency([row["end_to_end_seconds"] for row in rows]),
        "components": {
            component + "/" + model: {
                **latency(
                    [
                        c["latency_seconds"]
                        for c in calls
                        if (c["component"], c["model"]) == (component, model)
                    ]
                ),
                "cost_usd": total_cost(
                    [
                        c
                        for c in calls
                        if (c["component"], c["model"]) == (component, model)
                    ]
                ),
            }
            for component, model in groups
        },
    }


def total_cost(calls: list[dict[str, Any]]) -> float | None:
    costs = [c["cost_usd"] for c in calls]
    return sum(costs) if costs and all(c is not None for c in costs) else None


def require_live(result: dict[str, Any]) -> None:
    if (
        result.get("mode") != "live"
        or result.get("status") != "MEASURED"
        or not result.get("rows")
    ):
        raise ValueError("Completed live evaluation evidence is required")
    if any(c.get("source") != "live" for r in result["rows"] for c in r["calls"]):
        raise ValueError("Test-double calls cannot be reported as live")
    for row in result["rows"]:
        for call in row["calls"]:
            component = call.get("component")
            if (
                component not in COMPONENTS
                or call.get("model")
                != result["config"]["models"][result["assignment"][component]]
            ):
                raise ValueError(
                    "Call telemetry does not match the experiment assignment"
                )
    expected_cohort = {
        (family, repetition)
        for family in FIXTURES
        for repetition in range(result["config"]["repetitions"])
    }
    actual_cohort = {
        (row["migration_family"], row["repetition"]) for row in result["rows"]
    }
    if actual_cohort != expected_cohort:
        raise ValueError("Incomplete frozen benchmark cohort")
    expected = len(FIXTURES) * result["config"]["repetitions"]
    if len(result["rows"]) != expected or any(
        sum(r["migration_family"] == name for r in result["rows"])
        != result["config"]["repetitions"]
        for name in FIXTURES
    ):
        raise ValueError("Incomplete frozen benchmark")


def compare(
    baseline: dict[str, Any], candidate: dict[str, Any], component: str
) -> dict[str, Any]:
    require_live(baseline)
    require_live(candidate)
    if baseline["assignment"] != assignment() or candidate["assignment"] != assignment(
        component
    ):
        raise ValueError("Substitution must change exactly one component from Sol")
    for key in ("config", "fingerprint", "environments"):
        if baseline[key] != candidate[key]:
            raise ValueError(f"Comparison changed {key}")
    b, c = summarize(baseline["rows"]), summarize(candidate["rows"])
    delta = {
        key: (
            c["quality"][key] - b["quality"][key]
            if c["quality"][key] is not None and b["quality"][key] is not None
            else None
        )
        for key in QUALITY
    }
    config = baseline["config"]
    answer: dict[str, Any] = {
        "component": component,
        "decision": "INCONCLUSIVE",
        "quality_difference": delta,
        "Sol": b,
        "Terra": c,
        "average_cost_difference_usd": None,
        "p95_latency_difference_seconds": None,
        "average_latency_difference_seconds": None,
        "reason": "Missing quality labels or component coverage",
    }
    bl = b["components"].get(component + "/" + config["models"]["Sol"])
    cl = c["components"].get(component + "/" + config["models"]["Terra"])
    if bl and cl:
        answer["average_latency_difference_seconds"] = (
            cl["average_seconds"] - bl["average_seconds"]
        )
        answer["p95_latency_difference_seconds"] = cl["p95_seconds"] - bl["p95_seconds"]
    if b["average_cost_usd"] is not None and c["average_cost_usd"] is not None:
        answer["average_cost_difference_usd"] = (
            c["average_cost_usd"] - b["average_cost_usd"]
        )
    # Quality takes precedence even when cost or tail-latency evidence is unavailable.
    if any(
        value is not None and value * QUALITY[key] < -config["quality_tolerance"]
        for key, value in delta.items()
    ):
        answer.update(
            decision="KEEP_SOL", reason="Measured quality loss exceeds tolerance"
        )
        return answer
    if any(value is None for value in delta.values()):
        return answer
    for result in (baseline, candidate):
        for row in result["rows"]:
            if any(
                row.get(field) is None
                for field in (
                    "regressions_introduced",
                    "unnecessary_modification",
                    "safety_preserved",
                )
            ):
                answer["reason"] = "Incomplete independent quality annotations"
                return answer
            if row.get("reviewer_usage", 0) and row.get("reviewer_correct") is None:
                answer["reason"] = "Reviewer ground truth is incomplete"
                return answer
    if (
        not bl
        or not cl
        or min(bl["count"], cl["count"]) < config["minimum_component_calls"]
    ):
        return answer
    if answer["average_cost_difference_usd"] is None or b["average_cost_usd"] <= 0:
        answer["reason"] = "Actual usage and configured pricing required"
        return answer
    savings = 1 - c["average_cost_usd"] / b["average_cost_usd"]
    if savings < config["minimum_cost_savings_fraction"]:
        answer.update(
            decision="KEEP_SOL",
            reason="Cost savings below configured meaningful threshold",
        )
    elif cl["p95_seconds"] > bl["p95_seconds"] * (
        1 + config["maximum_p95_slowdown_fraction"]
    ):
        answer["reason"] = (
            "p95 exceeds 20% guideline; explicit cost/quality justification required"
        )
    else:
        answer.update(
            decision="USE_TERRA",
            reason="Quality preserved, meaningful savings, p95 within guideline",
        )
    return answer


def final_assignment(
    baseline: dict[str, Any], candidates: dict[str, Any]
) -> dict[str, str]:
    require_live(baseline)
    if set(candidates) != set(COMPONENTS):
        raise ValueError("All six isolated experiments are required")
    decisions = {name: compare(baseline, candidates[name], name) for name in COMPONENTS}
    if any(d["decision"] == "INCONCLUSIVE" for d in decisions.values()):
        raise ValueError(
            "Final selection requires conclusive evidence for every component"
        )
    return {
        name: "Terra" if d["decision"] == "USE_TERRA" else "Sol"
        for name, d in decisions.items()
    }
