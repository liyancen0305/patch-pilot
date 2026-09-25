"""One validated model boundary with durable telemetry."""

import json
import os
import time
import urllib.request
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any, Protocol, TypeVar

from pydantic import BaseModel, ValidationError

from patchpilot.evaluation.pricing import call_cost, environment_pricing

from .schema import ModelCallRecord
from .store import RunStore

T = TypeVar("T", bound=BaseModel)


class ModelBackend(Protocol):
    def complete(self, component: str, payload: dict[str, Any], schema: type[T]) -> tuple[dict[str, Any], int, int]: ...


def strict_output_schema(model: type[BaseModel]) -> dict[str, Any]:
    """Derive the Responses strict JSON Schema from the local Pydantic contract."""
    def normalize(value: Any) -> Any:
        if isinstance(value, list):
            return [normalize(item) for item in value]
        if not isinstance(value, dict):
            return value
        result = {key: normalize(item) for key, item in value.items()
                  if key not in {"title", "default", "minItems", "maxItems",
                                 "minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum",
                                 "minLength", "maxLength"}}
        if "definitions" in result:
            result["$defs"] = result.pop("definitions")
        if "$ref" in result:
            result["$ref"] = result["$ref"].replace("#/definitions/", "#/$defs/")
        if result.get("type") == "object":
            result["additionalProperties"] = False
            result["required"] = list(result.get("properties", {}))
        return result
    normalized = normalize(model.schema())
    assert isinstance(normalized, dict)
    return normalized


class SolBackend:
    """OpenAI Responses API adapter; credentials come from the environment."""

    model = "gpt-5.6-sol"

    def complete(self, component: str, payload: dict[str, Any], schema: type[T]) -> tuple[dict[str, Any], int, int]:
        key = os.environ.get("OPENAI_API_KEY")
        if not key:
            raise RuntimeError("OPENAI_API_KEY is required for a live Sol run")
        roles = {
            "Migration Planner": "Plan only requested migration changes; do not generate code.",
            "Patch Generator": "Generate only the planned migration patch.",
            "Failure Analyzer": "Analyze verification failures using evidence; do not approve or edit code.",
            "Change Reviewer": "Independently review the proposed repair and decide approval, rejection, or more evidence.",
            "Repair Generator": "Generate only the approved repair files; preserve regression behavior.",
            "CapabilityClassifier": "Classify ambiguous migration scope only; do not plan or edit code.",
        }
        body = json.dumps({
            "model": self.model,
            "input": [
                {"role": "system", "content": roles.get(component, "Make only requested migration changes.")},
                {"role": "user", "content": json.dumps({"component": component, "data": payload})},
            ],
            "text": {"format": {"type": "json_schema", "name": schema.__name__,
                                "strict": True, "schema": strict_output_schema(schema)}},
        }).encode()
        request = urllib.request.Request(
            "https://api.openai.com/v1/responses", data=body,
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=120) as response:
            result = json.load(response)
        if result.get("status") not in (None, "completed"):
            raise ValueError(f"Responses API status: {result.get('status')}; {result.get('error')}")
        content = "".join(part.get("text", "") for output in result.get("output", [])
                          for part in output.get("content", []) if part.get("type") == "output_text")
        usage = result.get("usage", {})
        if any(not isinstance(usage.get(key), int) or usage[key] < 0
               for key in ("input_tokens", "output_tokens")):
            raise ValueError("Responses API did not provide valid token usage")
        return json.loads(content), usage["input_tokens"], usage["output_tokens"]


class ModelClient:
    def __init__(self, backend: ModelBackend, store: RunStore, retries: int = 1) -> None:
        self.backend = backend
        self.store = store
        self.retries = retries

    def call(self, run_id: str, component: str, payload: dict[str, Any],
             schema: type[T], on_failure: Callable[[Exception, int, bool], None] | None = None) -> T:
        last_error: Exception | None = None
        for attempt in range(self.retries + 1):
            started = time.monotonic()
            output: dict[str, Any] | None = None
            input_tokens = output_tokens = 0
            try:
                output, input_tokens, output_tokens = self.backend.complete(component, payload, schema)
                parsed = schema.parse_obj(output)
                error = None
            except (ValueError, ValidationError, RuntimeError, OSError) as exc:
                last_error = exc
                error = str(exc)
                parsed = None
            model = getattr(self.backend, "model", "unknown")
            pricing = getattr(self.backend, "config", {}).get("pricing")
            if pricing is None:
                pricing = environment_pricing()
            live = isinstance(self.backend, SolBackend) or getattr(self.backend, "live", False)
            cost = call_cost(pricing, model, input_tokens if output is not None else None,
                             output_tokens if output is not None else None, live=live)
            try:
                run = self.store.load(run_id)
                prompt_name, prompt_version, attempt_number = (
                    run.prompt_name, run.prompt_version, run.attempt_number)
            except KeyError:
                prompt_name, prompt_version, attempt_number = "02_happy_path_e2e", "v1.1", 1
            self.store.record_model_call(ModelCallRecord(
                run_id=run_id, attempt_number=attempt_number, component=component,
                model=getattr(self.backend, "model", "unknown"),
                prompt_name=prompt_name, prompt_version=prompt_version,
                input_metadata={"pricing_version": pricing.get("version"),
                                "source": "live" if live else "test_double",
                                "retry": attempt + 1, "workflow_attempt": attempt_number, "context_files": payload.get("context_files", []),
                                "characters": len(json.dumps(payload))},
                input_tokens=input_tokens, output_tokens=output_tokens,
                latency_seconds=time.monotonic() - started,
                estimated_cost_usd=cost, structured_output=output, error=error,
                timestamp=datetime.now(timezone.utc).isoformat(),
            ))
            if parsed is not None:
                return parsed
            if on_failure is not None and last_error is not None:
                on_failure(last_error, attempt + 1, attempt < self.retries)
        raise RuntimeError(f"invalid {component} output after retries: {last_error}")
