"""Run the Prompt 2 workflow with the Sol backend."""

import argparse
import json
from pathlib import Path

from .model import ModelClient, SolBackend
from .runner import VerificationRunner, Workflow
from .store import RunStore


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--canonical", type=Path, required=True)
    parser.add_argument("--artifacts", type=Path, required=True)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--verification-python", type=Path, required=True)
    parser.add_argument("--approval", choices=("APPROVE", "DECLINE"), required=True)
    parser.add_argument("--repair", action="store_true", help="enable Prompt 3 bounded repair")
    args = parser.parse_args()
    store = RunStore(args.database)
    client = ModelClient(SolBackend(), store)
    run = Workflow(store, client, VerificationRunner(args.verification_python),
                   repair_enabled=args.repair).run(
        args.canonical, args.artifacts, approval=args.approval)
    print(json.dumps({"run_id": run.run_id, "state": run.current_state.value,
                      "final_status": run.final_status, "target_branch": run.target_branch}))


if __name__ == "__main__":
    main()
