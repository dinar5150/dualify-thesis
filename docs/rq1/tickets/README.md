# RQ1 implementation tickets

**Status:** documented and ready for future agent assignment; **none started**. The user approved the six-ticket plan, but the current task ends after writing and checking Markdown. See [../SPEC.md](../SPEC.md), [../PROTOCOL.md](../PROTOCOL.md), [../../../AGENTS.md](../../agent/AGENT_GUIDE.md).

## Dependency graph

```text
01 Frozen benchmark and leakage audit
  ↓
02 One native extraction attempt with temperature and fault provenance
  ↓
03 Four-candidate pool with crash-safe transcript and strict replay
  ↓
04 Offline gold scoring and pass@k report
  ↓
05 Full dev run, independent review, freeze → STOP
  ↓  (requires fresh user authorization)
06 One held-out test campaign and thesis result
```

| Ticket | What it delivers | Blocked by | Authorization |
| --- | --- | --- | --- |
| [01 — Benchmark split and audit](01-benchmark-split-and-audit.md) | Reproducible 10/30 manifest and leakage report, no API calls | None | Future implementation |
| [02 — Native candidate attempt](02-native-attempt-and-telemetry.md) | One observable full native extraction with T>0 initial generation / T=0 repair | 01 | Future implementation |
| [03 — Pool, recording and replay](03-candidate-pool-and-replay.md) | Four distinct slot IDs, crash-resume and strict offline replay for one task | 02 | Future implementation |
| [04 — Oracle and analytics](04-offline-oracle-and-analytics.md) | End-to-end offline pass@k low/high, delta, intervals and latency diagnostics | 03 | Future implementation |
| [05 — Dev campaign and freeze](05-dev-campaign-and-freeze.md) | 10-task dev evidence, review and **READY FOR HELD-OUT TEST** gate | 04 | Future live dev run after offline tests |
| [06 — Held-out study](06-heldout-test-and-report.md) | Frozen 30-task test evidence and final RQ1 results | 05 **and separate explicit user go-ahead** | Not authorized now |

## Ticket format

Every ticket contains **Problem**, **Known facts**, **Constraints**, **Hypotheses**, **Expected outcome** and **Stopping criteria**, plus **Blocked by**, **Acceptance criteria** and **Out of scope**. Status `ready-for-agent` means the ticket is prepared, not that its predecessors have completed. An agent may start only at the **unblocked frontier**, and must stop as soon as its ticket's criterion passes or a documented blocker prevents completion.

## Procedure for an agent working on one ticket

1. Read the ticket's blockers, the applicable spec/protocol and [original-method limitations](../../agent/KNOWN_DUALIFY_LIMITATIONS.md) before examining original upstream behavior. Reuse the existing diagnosis and preserve the original Z3 oracle.
2. Write the smallest full path to a verifiable outcome. Preserve baseline prompts/repairs/solver and existing tests.
3. Run mock/offline tests first, then permitted live checks only if the ticket and current user authorization allow them.
4. Attach commands, outputs, diffs and known limitations; update the bug register and decision register only for actually substantiated changes.
5. **Stop.** Do not select another ticket automatically, and do not run held-out test as a byproduct of dev completion.

Any future change to a frozen methodological decision needs a new documented and approved protocol amendment. Ticket completion cannot silently override the research agreement.
