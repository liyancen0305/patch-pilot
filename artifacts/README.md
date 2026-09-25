# Artifact navigation

Committed examples are **CONTROLLED / TEST-DOUBLE EVALUATION** unless explicitly
stated otherwise. There are no measured live Sol/Terra experiments in this repository.
Absolute paths and timestamps in historical records describe the machine/run that
produced them, not paths that must exist on your machine.

| Location | What to inspect |
| --- | --- |
| [benchmark/prompt4_summary.json](benchmark/prompt4_summary.json) | Five fixed families; separate happy and repair scenarios. Use per-run final states and verification results when assessing a particular scenario. |
| [benchmark/runs/](benchmark/runs/) | Plans, selected context, proposals, failures, reviews, repairs, approval, diffs, SQLite snapshots, and Git bundles. |
| [evaluation/model_tradeoffs.md](evaluation/model_tradeoffs.md) | Methodology and explicit deferral of live measurements. |
| [evaluation/component_comparisons.json](evaluation/component_comparisons.json) | All six substitutions remain INCONCLUSIVE; no selected winner. |
| [evaluation/validation_summary.json](evaluation/validation_summary.json) | Historical Prompt 6 harness validation, not model performance. |
| [validation/](validation/) | Final portfolio-cleanup regression report and audit summary. |
| `controlled-*/`, `controlled-repair-*/` | Historical Prompt 2/3 demonstrations; a new demo writes a fresh directory. |

Start with the [annotated Pydantic run](../docs/example_run.md) rather than reading
full logs. Generated target repositories and scratch databases are ignored; exported
per-run evidence is intentionally retained. Git bundles can retain checkpoints after
temporary sandboxes have been removed. SQLite holds state/history and serialized
run details; the JSON exports make those records inspectable without SQL tooling.

## Interpret historical telemetry carefully

Older controlled-run summaries contain zero token/cost placeholders and wall-clock
latencies for scripted responses. **Those are not measured live usage, billing, or
provider latency**, and are not used to make model-selection claims. Historical
records are preserved rather than retroactively rewriting observed evidence.
Current evaluation artifacts use null for unmeasured provider metrics.

The aggregate family `verification_status` in the Prompt 4 summary describes its
happy path. For example, Celery's happy path passed, but the separate `max3` run
failed sandbox verification and correctly ended at `NEEDS_HUMAN_REVIEW` without
target verification. Consult the per-run row for that distinction.

Model-call input metadata is not a full request transcript. Selected context,
structured outputs, diffs, and failure/review records explain decisions, but exact
provider request replay is not guaranteed. Approval records in the demos name
`simulated-human`; no interactive or authenticated approval interface is claimed.
