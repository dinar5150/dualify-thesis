# Ticket 01 — Frozen benchmark split and leakage audit

**Blocked by:** None — can start immediately  
**Status:** READY — only when blockers are satisfied  
**Scope:** RQ1 research branch; follow [approved specification](../SPEC.md).

## Problem
Original 40-case inputs need stable identity, an immutable group-aware 10/30 split and a documented leakage inventory before model calls.

## Known facts
The original benchmark has 40 YAML gold references and 40 associated evaluation Python files. Multiple records share similar functions. p01/p02 consume raw extracted source/spec.

## Constraints
Leave both benchmark directories unchanged; group near-duplicate examples together; use stable SHA256 identity and fixed seed; do not expose gold in prompts or use test gold for tuning.

## Hypotheses
An audit will reveal existing annotation leakage and generic informal specs; the distribution is descriptive and not an exclusion rule.

## Expected outcome
A committed manifest contains all 40 unique IDs, 10 dev/30 test with no group leakage, source/gold hashes and an audit report with case-level findings.

## Stopping criteria
Stop once all 40 mappings and hashes validate, counts are 10/30, no source/gold bytes changed, and deterministic offline tests cover grouping and audit. Do not run any LLM.

**Completion discipline:** Update [STATUS.md](../STATUS.md) with evidence; add any discovered defect to [KNOWN_BUGS.md](../../../KNOWN_BUGS.md). The AI agent must not expand this ticket into unrelated architecture or subsequent tickets.
