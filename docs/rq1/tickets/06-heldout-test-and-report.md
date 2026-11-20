# 06 — Execute one frozen held-out RQ1 evaluation and write thesis results

**Status:** ready-for-agent, **EXPLICITLY GATED / NOT AUTHORIZED**  
**Blocked by:** [05 — Dev campaign and freeze](05-dev-campaign-and-freeze.md) **AND a fresh, explicit user authorization after the dev gate**.  
**Deliverable:** One complete 30-task held-out evaluation (spec + code), replayable reports and an evidence-backed thesis RQ1 conclusion.

## Problem
Dev results alone cannot substantiate the final study. But executing test early or adapting the method after viewing outcomes makes the supposedly held-out sample a tuning set. The final run must be a separately authorized, frozen protocol that reports uncertainty and provider limitations honestly.

## Known facts
- Exactly **30 test** tasks are assigned by Ticket 01, with **300 planned full extractor attempt slots**: 30 × 2 channels × (1 baseline + 4 treatment).
- The approved estimator is combinatorial pass@k for n=4 and k={1,2,4}; primary effect is within-sampling-arm pass@4 minus pass@1 separately for both channels.
- The T=0 baseline is descriptive; strong claims of causal k-only advantage must refer to fixed-temperature treatment estimates.
- Gold equivalence is only for the original benchmark's supported fragment. Solver unknown and invalid candidates require separate reporting.
- The test campaign requires separate permission after Ticket 05 and no protocol tuning on test outcomes.

## Constraints
- Do not begin unless a **current written user authorization** references this ticket and the signed-off frozen code/config/manifest from Ticket 05.
- Confirm all source hashes, case assignments and provider model settings against freeze. No silent model switch, temperature search, benchmark edits, new retry policy, alternative scorer or extra k.
- Execute only the predeclared n=4+baseline per task/channel. Stop on unresolvable infrastructure/config errors; resume only within existing same-slot policy; document any required deviation and seek explicit decision before a rerun.
- Keep test gold inaccessible to live extraction. Candidate pool must be fully frozen and recorded before offline scoring.
- Report complete success/inconclusive/error taxonomy, conservative pass@k and optimistic unknown bounds, paired uncertainty, diversity/repair, latency with provider-policy caveats, and source-group/corpus limitations.
- Do not use test outcomes to edit protocol or make additional live attempts merely to improve coverage. Findings can be documented as follow-up research for RQ2/RQ3, not implemented here.

## Hypotheses
- **Descriptive research:** the magnitude of the oracle coverage gain from k=1 to k=4 can be estimated on held-out tasks, with uncertainty and additional cost. Pass@k nondecreasing is a mathematical consequence, not evidence of novelty.
- **Integrity:** one frozen, complete test campaign can be replayed and scored offline by a reviewer without Groq access.

## Expected outcome
- Exactly 300 recorded, integrity-verified held-out full extraction slots or a transparent `INCOMPLETE` study report (never fabricated completion).
- One reproducible report with separate spec/code pass@1/2/4 low/high, delta_4_1, 95% group-aware intervals, first-k diagnostic and baseline comparison.
- A clear written conclusion for thesis RQ1: estimated effect size, uncertainty, potential cases rescued by extra sampling, cost/latency, provider constraints and threats to validity.
- Evidence that all results were obtained with the freeze and no post-hoc tuning.

## Acceptance criteria
- [ ] Separate written approval and matching frozen hashes/config are logged before first test request.
- [ ] All 30 expected test case IDs are present; exactly 300 planned full attempt slots completed, or the experiment is flagged `INCOMPLETE` with transparent diagnostics.
- [ ] All treatment pools have n=4 and strict replay verifies request/response cardinality, prompt settings and candidate identities.
- [ ] Oracle scores preserve unknown/invalid distinctions; offline analysis runs without live API.
- [ ] Both channels show pass@1/2/4, per-task results, low/high, paired delta with 95% intervals, first-k diagnostic and source-group case counts.
- [ ] Performance cost, observed attempt latency, available HTTP metrics, retries/rate-limit waits and unavailable telemetry are distinctly reported.
- [ ] Thesis conclusion avoids unsupported causal/selection/whole-Python claims; test outcomes caused no unauthorized tuning.
- [ ] Review report and reproduction instructions reference the exact immutable artifacts.

## Stopping criteria
**STOP when:** the single frozen held-out campaign, offline reproduction and RQ1 report satisfy the acceptance criteria. If any indispensable slot cannot be completed within the predeclared limits, **STOP as `INCOMPLETE`** with an audit trail and request a new decision. Do not rerun or change the protocol on your own, begin RQ2, or continue polishing after the conclusion is supported.

## Out of scope
Unapproved test reruns, model hyperparameter search, new sampling methods, RQ2 selection and RQ3 fine-tuning.
