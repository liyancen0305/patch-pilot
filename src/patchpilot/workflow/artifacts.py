"""Durable, inspectable evidence for a Prompt 2 run."""

import json
import shutil
import sqlite3
import subprocess
from datetime import datetime
from pathlib import Path

from .store import RunStore


def export_run(store: RunStore, run_id: str, artifact_parent: Path) -> Path:
    run = store.load(run_id)
    destination = artifact_parent / "runs" / run_id
    destination.mkdir(parents=True, exist_ok=True)

    def write(name: str, value: object) -> None:
        (destination / name).write_text(json.dumps(value, indent=2, default=str) + "\n")

    write("run.json", json.loads(run.json()))
    write("state_history.json", [json.loads(item.json()) for item in store.history(run_id)])
    calls = store.model_calls(run_id)
    write("model_telemetry.json", [json.loads(item.json()) for item in calls])
    for name, value in (("migration_plan", run.plan), ("patch_proposal", run.proposal),
                        ("selected_context", run.context),
                        ("sandbox_verification", run.sandbox_verification),
                        ("approval", run.approval),
                        ("target_verification", run.target_verification)):
        if value is not None:
            write(f"{name}.json", json.loads(value.json()))
    if run.patch is not None and run.sandbox_verification and run.sandbox_verification.passed:
        (destination / "verified.patch").write_text(run.patch.diff)
        write("verified_patch.json", {"sha256": run.patch.sha256})
    bundle = artifact_parent / "sandbox-snapshot.bundle"
    if bundle.exists():
        shutil.copy2(bundle, destination / bundle.name)
    target = Path(run.repository_identifiers["target"])
    if run.target_branch and target.is_dir():
        diff = subprocess.run(["git", "diff", "main", run.target_branch], cwd=target,
                              text=True, capture_output=True, check=True).stdout
        (destination / "target_branch.diff").write_text(diff)
    with sqlite3.connect(store.path) as source, sqlite3.connect(destination / "run.sqlite3") as sink:
        source.backup(sink)
    duration = None
    if run.ended_at:
        duration = (datetime.fromisoformat(run.ended_at) - datetime.fromisoformat(run.started_at)).total_seconds()
    write("summary.json", {
        "run_id": run_id, "migration_goal": run.request.migration_goal,
        "model": "gpt-5.6-sol" if any(call.model == "gpt-5.6-sol" for call in calls) else
                 (calls[0].model if calls else None),
        "prompt_version": run.prompt_version, "final_state": run.current_state.value,
        "sandbox_verification_passed": run.sandbox_verification.passed if run.sandbox_verification else None,
        "approval": run.approval.decision if run.approval else None,
        "target_branch": run.target_branch,
        "target_verification_passed": run.target_verification.passed if run.target_verification else None,
        "attempt_count": run.attempt_number, "total_model_calls": len(calls),
        "input_tokens": sum(call.input_tokens for call in calls),
        "output_tokens": sum(call.output_tokens for call in calls),
        "estimated_cost_usd": sum(call.estimated_cost_usd or 0 for call in calls),
        "model_latency_seconds": sum(call.latency_seconds for call in calls),
        "end_to_end_latency_seconds": duration,
        "verified_patch_sha256": run.patch.sha256 if run.patch and run.sandbox_verification and run.sandbox_verification.passed else None,
        "final_status": run.final_status,
    })
    return destination
