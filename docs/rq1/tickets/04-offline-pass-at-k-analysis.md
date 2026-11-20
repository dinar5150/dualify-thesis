# Ticket 04 — Gold oracle pass@k and resource report

**Blocked by:** 03 — Four-slot candidate collection, checkpoint and strict replay  
**Status:** READY — only when blockers are satisfied  
**Scope:** RQ1 research branch; follow [approved specification](../SPEC.md).

## Problem
Original gold evaluation judges one extracted result at a time and lacks the thesis's pooled pass@k, uncertainty and cost reports.

## Known facts
Original `score_extraction_against_gold` calls the existing SMT checker; `contract_equivalent=False` can mean unknown rather than proved failure.

## Constraints
No edits to gold/Z3; offline analysis only; exactly n=4, k=1/2/4; use conservative known-good count and oracle-unknown sensitivity; 10,000 grouped paired bootstrap samples, frozen seed; no deduplication.

## Hypotheses
Measured gain Δ4,1 can be positive when tasks mix successes and failures; UNKNOWN bounds will expose conclusions not supported by solver.

## Expected outcome
A deterministic offline JSON/CSV/Markdown report shows both channels' pass@k, 95% intervals, Δ4,1, c/u distributions, repairs, diversity, errors, attempt latency and logical calls; physical HTTP/tokens labelled unavailable unless captured.

## Stopping criteria
Stop when synthetic c=0..4, unknown/invalid and duplicate tests pass, repeated offline analysis is deterministic, no network is possible, and empty/incomplete pools are rejected.

**Completion discipline:** Update [STATUS.md](../STATUS.md) with evidence; add any discovered defect to [KNOWN_BUGS.md](../../../KNOWN_BUGS.md). The AI agent must not expand this ticket into unrelated architecture or subsequent tickets.
