# Final cleanup validation

These reports validate the portfolio cleanup, not live provider quality or performance.
All model-driven scenarios are **CONTROLLED / TEST-DOUBLE EVALUATION**.

- [Regression summary](final_regression_summary.json): **137 passed, 0 failed, 0 skipped,
  0 pytest warnings reported**, using Python 3.12.3.
- [Complete pytest output](final_regression.txt) and [JUnit results](final_regression.xml).
- [Pydantic compatibility](pydantic_compatibility.json): all 32 schema contracts
  unchanged; 10 historical benchmark runs round-tripped through SQLite under
  Pydantic 2.13.5 with deprecation warnings treated as errors.
- [Pydantic v2 unit tests](pydantic_v2_unit_tests.xml): 9 passed with deprecation
  warnings treated as errors.
- [Cleanup audit](cleanup_audit.json): local documentation links, common credential
  patterns, unchanged benchmark inputs/evidence, and unchanged Orchestrator/schema
  ASTs apart from compatibility imports.

The existing state-machine, happy-path, bounded-repair, benchmark, guardrail,
persistence, and evaluation-harness tests all passed. Deliberately failed migration
checks inside repair/escalation scenarios are expected test inputs, not failed
regression tests. The fixture verification script also passed its seven tests,
mypy, Ruff, and runtime import check.

No deprecation warnings remained in these validation runs. Old APIs in immutable
benchmark fixtures and their historical logs remain intentionally preserved as
migration input/evidence. These results do not establish live model competence,
provider cost, or provider mean/p95 latency. Live provider benchmarking is
**NOT MEASURED / DEFERRED**.
