# 04 — Turn recorded candidates into an auditable offline RQ1 report

**Status:** ready-for-agent (NOT STARTED)  
**Blocked by:** [03 — Candidate pool and strict replay](03-candidate-pool-and-replay.md).  
**Deliverable:** A credential-free, end-to-end offline report from immutable recorded candidate pools through native gold scoring to pass@k, uncertainty and costs.

## Problem
A raw boolean gold score hides the difference between a decisively incorrect contract, invalid expression and solver `unknown`. Counting all false results as “incorrect” understates uncertainty. Computing pass@k by taking a first-k prefix alone is not the agreed estimator, and treating four samples from the same task as independent observations would give misleading confidence intervals.

## Known facts
- Original Dualify has `score_extraction_against_gold`, a human-confirmed gold corpus and Z3 equivalence checking, including reasons/diagnostics.
- A false equivalence flag does not necessarily prove non-equivalence; unknown or parse failure needs explicit classification.
- The approved primary estimator uses n=4, k={1,2,4}, separate spec/code task macro-averages and a conservative/unknown-sensitive bound.
- The within-treatment effect of interest is `pass@4 − pass@1`. The T=0 baseline is separate and descriptive.
- Observed extractor elapsed time is **not** pure provider inference latency, especially under Groq rate limits and retries.

## Constraints
- Score **only** fully completed, integrity-verified pools from Ticket 03. Incomplete campaigns fail, not shrink n.
- Invoke the existing gold scorer; preserve original Z3 timeout, checker and formula fragment semantics. Consult [original-method limitations](../../agent/KNOWN_DUALIFY_LIMITATIONS.md) and report baseline defects without modifying Z3. No invented oracle, new solver algorithm or LLM judge.
- Classify each candidate as `equivalent`, `non_equivalent`, `invalid`, `inconclusive`, or `unclassified/blocked` if native evidence is insufficient.
- Compute `low(k)=1−C(4−c,k)/C(4,k)` and `high(k)=1−C(4−c−u,k)/C(4,k)`. Reject impossible counts and preserve diagnostics.
- Macro-average per task/channel; use group-aware **paired** bootstrap intervals with recorded random seed, effective groups and iteration count.
- Keep the reference truth and derived labels in offline scoring artifacts only; candidate generation/replay must remain independent of them.
- Report mandatory attempt wall time and stage metrics. Provider-internal HTTP/latency/tokens are conditional on observed telemetry and may be NA with explanation.
- Tests must be fully offline, fast and deterministic.

## Hypotheses
- **Methodological hypothesis:** native equivalence results can be mapped to honest confirmed-success and uncertainty bounds without changing the oracle.
- **Engineering hypothesis:** both channels can be evaluated with one reusable offline analyzer that detects missing/corrupt pools before reporting numbers.

## Expected outcome
- A small deterministic fixture from a recorded candidate pool generates per-candidate reasons, per-task low/high pass@1/2/4 and separate channel macro summaries.
- A single offline report includes paired delta_4_1 and 95% group-aware interval, first-k diagnostic, mixed-outcome cases, degraded/repair/error distribution, diversity and observable costs.
- A second invocation on identical records reproduces identical numerical results and artifact checksums, without credentials.

## Acceptance criteria
- [ ] Formula fixtures: c=0 → 0; c=1,u=0 → (0.25,0.5,1.0); c=4 → 1; c=0,u=1 → high (0.25,0.5,1.0).
- [ ] Solver `unknown` contributes to u, not decisively incorrect; invalid syntax contributes to neither c nor u. Native reasons are preserved.
- [ ] Every test task is weighted equally within its channel; paired resampling preserves task/group relationships and yields reproducible 95% interval.
- [ ] Treatment comparison uses **within-temperature** k=4 vs k=1; T=0 baseline is labeled descriptive, not used as a k-only control.
- [ ] Reports include formula diversity, error statuses, native repair counts, observed attempt/campaign timings, and unknown/incomplete/NA counts.
- [ ] A missing slot, contradictory counts, unclassifiable oracle state or transcript corruption produces a **failed report** with a diagnostic, not plausible numbers.
- [ ] Offline reruns match numerical outputs and verify no network/model access. Existing gold/solver regression checks remain green.

## Stopping criteria
**STOP when:** every boundary fixture and one end-to-end offline case passes; the report explains oracle uncertainty and observed/missing telemetry; an independent reviewer can reproduce its values without Groq. If native scoring cannot distinguish a crucial oracle status, record `BLOCKED` and propose only the narrowest observation improvement. Do not run a dev campaign or tune results toward a desired pass@k.

## Out of scope
Provider sampling, selecting a best contract, test-set evaluation, model comparison and modifying Z3 internals.
