# RQ1 tickets — tracer bullets

Each ticket is one verifiable vertical slice; use the exact six-section structure below. Dependencies: **01 → 02 → 03 → 04 → 05 → [separate authorization] → 06**.

| # | Title | State |
|---|---|---|
| 01 | [Frozen benchmark split and leakage audit](01-freeze-benchmark-and-audit.md) | READY — follow dependencies |
| 02 | [One auditable native extractor attempt](02-candidate-attempt-client.md) | READY — follow dependencies |
| 03 | [Four-slot candidate collection, checkpoint and strict replay](03-candidate-pools-and-replay.md) | READY — follow dependencies |
| 04 | [Gold oracle pass@k and resource report](04-offline-pass-at-k-analysis.md) | READY — follow dependencies |
| 05 | [Bounded live dev and independent review](05-dev-verification-and-review.md) | READY — follow dependencies |
| 06 | [Frozen held-out evaluation — requires separate authorization](06-heldout-test-evaluation.md) | BLOCKED — held-out authorization |

Workflow: open the first ticket with satisfied blockers, read [SPEC](../SPEC.md), implement with deterministic tests, run its stopping checks, record any bugs in [KNOWN_BUGS](../../../KNOWN_BUGS.md), then move forward. Keep completed tickets as auditable artifacts rather than rewriting them into descriptions of unrelated refactors.
