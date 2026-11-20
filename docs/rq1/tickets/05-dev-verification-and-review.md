# Ticket 05 — Bounded live dev and independent review

**Blocked by:** 01–04 — All previous technical tickets  
**Status:** READY — only when blockers are satisfied  
**Scope:** RQ1 research branch; follow [approved specification](../SPEC.md).

## Problem
We need evidence the end-to-end pipeline is correct and reproducible before touching held-out test.

## Known facts
The frozen dev has 10 cases; each uses 2 channels × (1 T=0 baseline + 4 sampling) = 100 full attempt slots. Groq limits may cause backoff/timeouts.

## Constraints
Preflight must pass offline tests/lint/type checks; use only locked actual Qwen/Groq config; resume transport faults without rewriting finished slots; inspect dev only. Review standards and experimental validity on independent axes.

## Hypotheses
Dev exposes engineering issues and verifies replay/cost semantics, not statistical claims about held-out performance.

## Expected outcome
Exactly one complete dev candidate campaign (or documented BLOCKED/INCOMPLETE), matching repeatable offline reports, verified error metrics, review findings and frozen README/config/code fingerprints.

## Stopping criteria
Stop immediately at READY FOR HELD-OUT TEST after all hard gates pass. If API key/account access is missing, mark BLOCKED and stop rather than guessing or using synthetic results as live evidence. No full test or endless polishing.

**Completion discipline:** Update [STATUS.md](../STATUS.md) with evidence; add any discovered defect to [KNOWN_BUGS.md](../../../KNOWN_BUGS.md). The AI agent must not expand this ticket into unrelated architecture or subsequent tickets.
