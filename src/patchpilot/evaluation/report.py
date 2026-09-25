"""Readable reports derived only from persisted evaluation evidence."""

from pathlib import Path
from typing import Any


def write_tradeoffs(
    directory: Path,
    comparisons: list[dict[str, Any]],
    status: str,
    selected: dict[str, str] | None = None,
) -> None:
    lines = [
        "# Model Selection & Trade-offs",
        "",
        f"Status: **{status}**",
        "",
        "Prompt: 06_model_optimization_eval / v1",
        "",
        "| Component | Decision | Assignment | Reason |",
        "| --- | --- | --- | --- |",
    ]
    for item in comparisons:
        component = item["component"]
        reason = item["reason"].replace("|", "\\|").replace("\n", " ")
        lines.append(
            f"| {component} | {item['decision']} | "
            f"{selected[component] if selected else 'Pending'} | {reason} |"
        )
    lines += [
        "",
        "Quality, cost, average latency, p95, denominators, and full configuration",
        "are retained in component_comparisons.json and the experiment JSON files.",
        "Test-double results cannot establish live model quality or performance.",
        "Selection alone does not confirm combined quality; inspect optimized_results.json and adjudicate it.",
        "",
    ]
    (directory / "model_tradeoffs.md").write_text("\n".join(lines))
