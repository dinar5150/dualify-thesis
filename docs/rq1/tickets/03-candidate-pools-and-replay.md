# Ticket 03 — Four-slot candidate collection, checkpoint and strict replay

**Blocked by:** 02 — One auditable native extractor attempt  
**Status:** READY — only when blockers are satisfied  
**Scope:** RQ1 research branch; follow [approved specification](../SPEC.md).

## Problem
A repeated prompt can cause original prompt-hash replay to reuse the last recorded response, falsely inflating pass@k. Interrupted Groq sessions must not silently overwrite completed outputs.

## Known facts
Upstream `ReplayLLMClient` has sequential replay and prompt-based replay; prompt-based mode can repeat the last answer. `ResumingLLMClient` can reuse successful prefixes.

## Constraints
Create 4 numbered independent intervention slots + 1 baseline per case/channel; each slot has its own immutable transcript, source hash and model config. On recoverable interruption resume the SAME slot only. Preserve real duplicates.

## Hypotheses
Strict replay with temperature/hash verification will reject phantom candidates and identify incomplete groups; interrupted valid-prefix replay can reduce unnecessary calls.

## Expected outcome
Frozen candidate pools with unique provenance, bounded resumability and offline exact transcript replay; the analyzer can reject any group with fewer than four completed slots.

## Stopping criteria
Stop when deterministic tests reject missing/excess/mismatched calls, replays yield exactly recorded outputs, duplicate formulas remain separate, and incomplete slots fail completeness checks. No new model sampling beyond dev budget.

**Completion discipline:** Update [STATUS.md](../STATUS.md) with evidence; add any discovered defect to [KNOWN_BUGS.md](../../../KNOWN_BUGS.md). The AI agent must not expand this ticket into unrelated architecture or subsequent tickets.
