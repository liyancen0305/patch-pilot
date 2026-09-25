"""Versioned provider pricing. Unknown usage or prices never become zero cost."""

import math
import os
from typing import Any


def call_cost(
    pricing: dict[str, Any],
    model: str,
    input_tokens: int | None,
    output_tokens: int | None,
    *,
    live: bool,
) -> float | None:
    if not live or input_tokens is None or output_tokens is None:
        return None
    rates = pricing.get("usd_per_million_tokens", {}).get(model, {})
    values = (rates.get("input"), rates.get("output"))
    if any(value is None for value in values):
        return None
    if any(
        not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0
        for value in (*values, input_tokens, output_tokens)
    ):
        raise ValueError("pricing and token counts must be finite and nonnegative")
    return float(input_tokens * values[0] + output_tokens * values[1]) / 1_000_000


def environment_pricing() -> dict[str, Any]:
    """Compatibility with explicit legacy Sol rates, without assumed defaults."""

    def optional_rate(name: str) -> float | None:
        value = os.environ.get(name)
        return float(value) if value is not None else None

    return {
        "version": "explicit-environment-v1",
        "source": "PATCHPILOT_SOL_INPUT_USD_PER_M / PATCHPILOT_SOL_OUTPUT_USD_PER_M",
        "usd_per_million_tokens": {
            "gpt-5.6-sol": {
                "input": optional_rate("PATCHPILOT_SOL_INPUT_USD_PER_M"),
                "output": optional_rate("PATCHPILOT_SOL_OUTPUT_USD_PER_M"),
            }
        },
    }
