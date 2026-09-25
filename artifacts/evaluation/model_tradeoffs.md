# Model Selection & Trade-offs

**Live provider model benchmarking: NOT MEASURED / DEFERRED.**
**OpenAI API key: NOT REQUIRED.**
**Real Sol/Terra cost and latency claims: NOT MADE.**

The portfolio deliverable is an evaluation framework validated with
**CONTROLLED / TEST-DOUBLE EVALUATION**, not a completed live model comparison.
No provider account, credits, or live calls are needed for the documented demos,
automated tests, or default evaluation-status command. Historical Prompt 6 metadata
recorded the absence of live access as blocked; this portfolio status records the
same unmeasured experiments as deferred. No measured result has been overwritten.

| Component | Decision | Final assignment | Evidence still missing |
| --- | --- | --- | --- |
| Migration Planner | INCONCLUSIVE | Pending | Live baseline and isolated substitution |
| Patch Generator | INCONCLUSIVE | Pending | Live baseline and isolated substitution |
| Failure Analyzer | INCONCLUSIVE | Pending | Live failure-analysis coverage |
| Repair Generator | INCONCLUSIVE | Pending | Live repair coverage |
| Change Reviewer | INCONCLUSIVE | Pending | Live review coverage and independent correctness labels |
| Capability Classifier | INCONCLUSIVE | Pending | Live ambiguous-request coverage |

The existing Sol adapter is an implementation default, not an evidence-selected
winner. There is no final mixed-model assignment or optimized live end-to-end run.
No live quality differences, token costs, dollar costs, average latencies, or p95
latencies are reported. Missing metrics stay null, rather than being invented as zero.

## Methodology implemented by the framework

1. Keep the five migration families, starting fixtures, architecture, verification,
   model prompts, and context budgets fixed. Record configuration, prompt version,
   source fingerprints, and verification environment versions.
2. Record the full all-Sol baseline before any substitutions. Restore it for each
   experiment and change only one of the six LLM components to Terra.
3. Assess success, first-pass/repair success, regressions, unnecessary modifications,
   human escalation, Reviewer correctness, and safety behavior before considering
   cost or speed. Independent quality annotations need an adjudicator and an
   evidence file whose hash is recorded.
4. Aggregate actual usage-based cost per call, component, run, and benchmark. Pricing
   assumptions are centralized and versioned. Test-double or unknown usage/prices
   cannot support live cost claims.
5. Compare mean and nearest-rank p95 latency, emphasizing p95 for tail behavior.
   **Approximately 20% p95 slowdown is a portfolio-level guideline, not a production
   SLA.** A larger slowdown stays inconclusive until explicitly justified on cost
   and quality; it is not automatically evidence that the cheaper model is unusable.
6. Require conclusive evidence for every assignment before running the chosen mixed
   configuration across the entire fixed benchmark. A mixed run still needs its own
   independent quality review; isolated comparisons do not establish combined quality.

Defaults in [configuration](../../config/model_evaluation.json) are zero tolerated
observed quality loss, at least 10% cost savings, and at least 20 calls for each
compared component/model. Sol and Terra IDs are configurable, unverified provider
assumptions. The three repetitions are a starting configuration, not sufficient
statistical evidence for production decisions.

## Measurement definitions

- Success is `READY_FOR_PR`. First-pass success also requires Attempt 1. All completed
  migration cases remain in the denominator, including failures and escalations.
- Repair success is conditional on reaching Attempt 2 or later. No opportunities
  means null. Human escalation is `NEEDS_HUMAN_REVIEW`.
- Regression and unnecessary-modification rates are per independently adjudicated
  run, not per edited line. Reviewer correctness and safety preservation also need
  evidence; a passing verification suite alone does not establish those labels.
- p95 is the sorted observation at one-based index `ceil(0.95 × n)`. Every retry is
  a separate timed call; component statistics include counts and mean latency.
- Call timing covers the provider adapter; end-to-end timing includes workflow tools.
  Synthetic call timing is not provider latency.
- Cost is reported input/output tokens times configured rates, not a provider invoice.
  Cached-token, batch, and tier discounts are not modeled. Unknown billed usage on
  failed calls leaves costs and dependent totals unknown.

## Inspect or validate without provider access

From the repository root, after the [project setup](../../README.md#how-to-run):

```bash
.venv/bin/python -m patchpilot.evaluation.runner
.venv/bin/python -m pytest tests/test_model_evaluation.py -ra
```

The first command records deferred status and makes no network/model calls. The
second runs deterministic harness tests, including a real-verifier controlled repair.
The existing optional provider adapter and opt-in experiment path remain for future
research; they are not the project's setup or acceptance path. No API-specific setup
is needed for this portfolio.

Quality annotation format, for a future measured run, is a JSON object keyed by
`run_id`, with `adjudicator`, `evidence_file`, and `labels`. Label fields are
`regressions_introduced`, `unnecessary_modification`, `reviewer_correct`, and
`safety_preserved`, each boolean or null. Never label an uncalled Reviewer correct.
The framework rejects test doubles as live evidence, changed cohorts/configurations,
partial experiments, insufficient coverage, and unsupported final selections. Existing
live experiment records cannot be silently overwritten.

## Limitations and artifact interpretation

Natural happy paths can bypass repair and review. Exact supported requests bypass
the semantic classifier. Reusing existing failure/ambiguity evidence in a separate
frozen replay study remains future work if natural runs cannot cover a component;
this cleanup did not add scenarios or change the benchmark.

Workflow contracts use a Pydantic compatibility namespace to avoid deprecation
warnings while retaining schema and persistence semantics. The freeze manifest was
refreshed for compatibility imports and an entrypoint description; fixtures and
workflow logic were not changed. Current deferred artifacts carry updated source
fingerprints; historical test reports and benchmark records retain their provenance.
Legacy workflow `model_type` recognizes the original Sol backend specifically, so
future mixed experiments should use evaluation `mode` and per-call `source`/`model`
as their authoritative provenance.

- [sol_baseline.json](sol_baseline.json): no baseline measurements.
- [component_comparisons.json](component_comparisons.json): six planned substitutions,
  all INCONCLUSIVE.
- [optimized_results.json](optimized_results.json): no selected assignment or optimized results.
- [validation_summary.json](validation_summary.json): historical Prompt 6 validation,
  covering 136 distinct tests across overlapping reports, not model performance.
- [Final cleanup validation](../validation/): current regression and compatibility checks.

Detailed model-call journals and workflow artifacts would be retained for an actual
experiment. Prior controlled artifact timing and zero-cost placeholders are not live
measurements; see the [artifact guide](../README.md).
