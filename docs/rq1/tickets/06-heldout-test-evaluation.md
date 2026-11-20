# Ticket 06 — Frozen held-out evaluation — requires separate authorization

**Blocked by:** 05 — Dev verification and review AND explicit researcher approval  
**Status:** BLOCKED — requires explicit test approval  
**Scope:** RQ1 research branch; follow [approved specification](../SPEC.md).

## Problem
The thesis eventually needs unbiased pass@k on 30 held-out tasks; running it during dev would invalidate the pre-registered holdout.

## Known facts
Expected campaign size is 30 × 2 × (1 + 4) = 300 extractor slots, potentially more physical LLM requests due to repair/retries.

## Constraints
No test calls until explicit approval; use the frozen version, model, T, benchmark, prompts and scoring; no test-led tuning or candidate replacement; gold remains evaluation-only.

## Hypotheses
The held-out estimate will quantify effect size, solver uncertainty and rate-limited cost within the supported verification fragment.

## Expected outcome
Candidate pool frozen before scoring, separately computed spec/code pass@1/2/4 and Δ4,1 with intervals and validity caveats, plus gold-free candidate export for RQ2.

## Stopping criteria
Stop when all 300 planned slots are accounted for, analysis/replay are deterministic and reported, or mark incomplete with explicit reason. Any method change requires a new study, not silent test reruns.

**Completion discipline:** Update [STATUS.md](../STATUS.md) with evidence; add any discovered defect to [KNOWN_BUGS.md](../../../KNOWN_BUGS.md). The AI agent must not expand this ticket into unrelated architecture or subsequent tickets.
