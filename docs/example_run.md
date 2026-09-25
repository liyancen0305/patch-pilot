# Example: Pydantic migration with one repair

**CONTROLLED / TEST-DOUBLE EVALUATION** using real sandbox and target verification.
This is persisted run `329dda9efc2947b7a2f8424e41a105d1`, not a claimed live-model success.
All evidence links below refer to the same recorded run.

| Step | Recorded evidence |
| --- | --- |
| Request and repository analysis | [Run record](../artifacts/benchmark/runs/pydantic/repair2/runs/329dda9efc2947b7a2f8424e41a105d1/run.json): upgrade Pydantic v1 to v2; discover dependency, model APIs, shared configuration, and regression tests. |
| Selected context | [Ranked snippets](../artifacts/benchmark/runs/pydantic/repair2/runs/329dda9efc2947b7a2f8424e41a105d1/selected_context.json), including parsing/serialization and validation tests, with scores, reasons, and budgets. |
| Migration plan | [Plan](../artifacts/benchmark/runs/pydantic/repair2/runs/329dda9efc2947b7a2f8424e41a105d1/migration_plan.json): update dependency, model APIs/configuration, and permitted test API calls while preserving behavior. |
| Initial patch | [Proposal](../artifacts/benchmark/runs/pydantic/repair2/runs/329dda9efc2947b7a2f8424e41a105d1/patch_proposal.json) is applied only in the sandbox. |
| Attempt 1 fails | [Repair evidence](../artifacts/benchmark/runs/pydantic/repair2/runs/329dda9efc2947b7a2f8424e41a105d1/repair_attempts.json): 2 pytest failures, 5 passes; email normalization no longer produces lowercase addresses. |
| Analyze and repair | [Analysis](../artifacts/benchmark/runs/pydantic/repair2/runs/329dda9efc2947b7a2f8424e41a105d1/failure_analyses.json) identifies `src/shop/users.py`. Deterministic repair policy approves this focused change; no Reviewer or context expansion is used. |
| Attempt 2 passes | The same [repair record](../artifacts/benchmark/runs/pydantic/repair2/runs/329dda9efc2947b7a2f8424e41a105d1/repair_attempts.json) contains the passing migration check, pytest, mypy, Ruff, and import checks. |
| Approval and target | [Approval](../artifacts/benchmark/runs/pydantic/repair2/runs/329dda9efc2947b7a2f8424e41a105d1/approval.json) records explicit `APPROVE` by `simulated-human`; the [verified patch](../artifacts/benchmark/runs/pydantic/repair2/runs/329dda9efc2947b7a2f8424e41a105d1/verified.patch) is transferred to a target branch. |
| Final verification | [Target checks](../artifacts/benchmark/runs/pydantic/repair2/runs/329dda9efc2947b7a2f8424e41a105d1/target_verification.json) pass; [summary](../artifacts/benchmark/runs/pydantic/repair2/runs/329dda9efc2947b7a2f8424e41a105d1/summary.json) ends at `READY_FOR_PR`, total attempts 2. |

The relevant repair excerpt is short:

```diff
-        value = value.strip()
+        value = value.lower()
```

The complete patch retains Pydantic's shared whitespace normalization. The diff is
not evidence by itself: the unchanged behavioral assertions and full verification
suite establish the tested outcome. This run did not need rollback; rollback and
max-attempt escalation are exercised in separate controlled scenarios.

To produce a fresh run after the [README setup](../README.md#how-to-run):

```bash
.venv/bin/python scripts/run_controlled_repair.py
```

The script prints the new run ID and artifact directory. Exact IDs, snapshots,
paths, and timing differ between runs. Approval is supplied explicitly by the demo;
the project does not include an authenticated human-approval UI or automatically
open, merge, or deploy a pull request.
