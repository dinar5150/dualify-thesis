# 01 — Freeze the original benchmark and audit leakage

**Status:** ready-for-agent (NOT STARTED)  
**Blocked by:** None — first unblocked ticket.  
**Deliverable:** A reproducible, validated 10-dev/30-test case manifest and a complete risk audit for the original 40 benchmark examples, without contacting Groq.

## Problem
The original Dualify benchmark contains only 40 reference-backed tasks and includes related function variants. Naive random splitting can put nearly identical examples into dev and test. Embedded formal annotations or weak informal descriptions can also complicate what “correct extraction” means. The research cannot proceed responsibly without a fixed, inspectable dataset boundary.

## Known facts
- The original upstream revision `7ffd1ae37822096d5b7b573785ee46e877903185` contains 40 `lifted_auto_eval` Python inputs paired with 40 human-confirmed `lifted` gold YAML references.
- Some source families have distinct variants of the same underlying function; grouping must inspect identity and semantic/source similarity, not just filename equality.
- Gold correctness is limited to the benchmark's supported logic fragment; original inputs may embed contract-like text.
- Q1, Q3 and Q4 require unchanged inputs plus a group-aware split of 10 dev and 30 held-out test.

## Constraints
- Treat original benchmark inputs and gold as immutable, byte-for-byte; record checksums.
- Each unique benchmark ID must appear exactly once, in one split. Keep all closely related examples together. Balance corpus origin and `needs_attention` where possible, and explain any necessary compromise.
- Produce the split before any live LLM experiment. Do not use performance or generated outputs to choose group assignment.
- Audit all cases for visible formal pre/post text, uninformative specs, source similarity, unusual reference quality and any generation/gold overlap. An audit finding does not authorize dropping or rewriting a case.
- Keep gold text out of prompts and runtime generation inputs. No code from previous fork branches is a source of truth.
- This ticket is an offline **vertical slice**: a user can run a command or script, inspect a manifest and audit, and get a definite validation result.

## Hypotheses
- **Engineering hypothesis:** a stable split and complete leakage audit can be generated with the fixed benchmark while keeping related functions grouped.
- If exact 10/30 conflicts with grouping, report the conflicting groups and stop for a documented decision rather than silently weakening either rule.

## Expected outcome
- One deterministic manifest with seed, group rule, 40 IDs, source provenance, group membership, 10/30 assignments, input/gold hashes and validation result.
- One case-level leakage/quality audit and summary counts, with clear flags rather than undocumented judgment.
- An offline, repeatable verification command with both positive and deliberately invalid-manifest tests.
- A visible status: `SPLIT_FROZEN` when all integrity checks succeed, or `BLOCKED` with exact reason.

## Acceptance criteria
- [ ] A fresh checkout of the original-upstream-based branch reproduces the same manifest and hashes with a fixed seed.
- [ ] Exactly 40 unique cases, exactly 10 dev/30 test, no group straddles the split; every gold contract maps to exactly one input.
- [ ] The report includes case-level annotations, similar-function groups, weak descriptions, corpus provenance and quality metadata.
- [ ] Tests reject missing/duplicate IDs, source drift, corrupt hashes and a duplicated function group split across dev/test.
- [ ] Running this ticket produces **zero** live LLM requests and no edits to original dataset/gold content.
- [ ] The verification record captures commands, versions, checksum and any documented compromises.

## Stopping criteria
**STOP when:** the manifest is stable and checked, audit covers all 40 cases, tests of valid/invalid examples pass, and the result is recorded as `SPLIT_FROZEN`. If a required grouping/split rule cannot be satisfied, stop as `BLOCKED` with evidence. Do not proceed to model sampling, model selection, refactoring or Ticket 02 automatically.

## Out of scope
Groq credentials, model sampling, pass@k estimation, changes to reference formulas and decisions based on held-out outcomes.
