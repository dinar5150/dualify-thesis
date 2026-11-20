# Ticket 02 — One auditable native extractor attempt

**Blocked by:** 01 — Frozen benchmark split and leakage audit  
**Status:** READY — only when blockers are satisfied  
**Scope:** RQ1 research branch; follow [approved specification](../SPEC.md).

## Problem
Original p01/p02 do not explicitly pass a sampling temperature. Each attempt can use repair, and original extraction may swallow provider exceptions. We need correct temperature routing and error visibility.

## Known facts
`LLMClient.generate_json(prompt,temperature=0.0)` exists. Original extractor performs initial/repair/safe-repair stages. Recording wrapper stores successful calls.

## Constraints
Preserve original prompts, validation, repair, parser, Z3 and fallback. The client wrapper changes only first logical call T; subsequent calls remain native T=0. Classify infra vs content/config errors without free redraws.

## Hypotheses
The same fake model response follows native processing at T=0; positive-T initial call creates diversity without modifying repair. Provider failure classification prevents silent slot completion.

## Expected outcome
One case/channel can be extracted through native p01/p02 and produce trace, original output, correct per-stage temperature, logical call count, elapsed time and transparent error status.

## Stopping criteria
Stop when mock parity tests prove T=0 initial/repair, positive-T initial with T=0 repairs, exhausted 429/timeout/5xx incomplete, generated JSON-format errors counted, and auth/config fatal. No live dev yet.

**Completion discipline:** Update [STATUS.md](../STATUS.md) with evidence; add any discovered defect to [KNOWN_BUGS.md](../../../KNOWN_BUGS.md). The AI agent must not expand this ticket into unrelated architecture or subsequent tickets.
