# 05 — Run the complete dev study, verify it independently, then freeze and STOP

**Status:** ready-for-agent (NOT STARTED; live dev not authorized by this documentation-only task)  
**Blocked by:** [04 — Offline oracle and analytics](04-offline-oracle-and-analytics.md).  
**Deliverable:** A fully reproducible **10-case dev campaign** with independent review, known issues documented, frozen methodology and a final `READY FOR HELD-OUT TEST` / `BLOCKED` verdict.

## Problem
Unit tests can confirm interfaces but not the stability of a real Groq-run campaign. Without a bounded dev gate, an agent may spend unlimited calls optimizing accuracy or proceed directly to test, contaminating held-out evaluation and undermining the thesis. Groq Free Tier rate limits and transport behavior can distort timing and error attribution.

## Known facts
- The approved split reserves exactly **10 dev** tasks; each gets one baseline and four treatment attempts on each of two channels: **100 full extraction attempt slots** for a complete dev run.
- Exact Qwen model ID and recommended positive temperature depend on the user's available Groq configuration and must be pinned before live work; no arbitrary model substitutions.
- Original native repair may issue extra LLM calls; provider transport retries further increase physical requests.
- RQ1 uses confirmed gold equivalence, conservative pass@k and unknown bounds, with attempt elapsed time and complete failure provenance.
- The user's agreed Definition of Done ends development **before** the held-out 30-case experiment.

## Constraints
- Enter this ticket only when Tickets 01–04 are green and the user has initiated the future implementation/dev phase. The current documentation task grants **no live API call**.
- Preflight and save model ID, mode, endpoint, T>0 from applicable guidance, T=0 baseline/repairs, timeout/retry/rate-limit policy, full dependency/source manifest and checksums. Reject missing fields.
- Run the predeclared complete dev plan with bounded API usage; stop after cap/exhaustion, no repeated sampling until “good-looking” metrics.
- Record real Groq status bodies, distinguish provider out-of-service/429/5xx from generated JSON-format errors and terminal client config failures. Resume only incomplete infrastructure slots. Record latency including wait/backoff.
- Verify strict replay, score offline and review benchmark leakage. Check behavior against known bugs.
- Fix only objective correctness/integrity issues revealed on dev. Document changes, rerun relevant tests and justified dev checks, and update [../../../KNOWN_BUGS.md](../../../KNOWN_BUGS.md). No performance chasing, added temperature sweep, extra k, or unplanned fine-tuning.
- Use an **independent reviewer/subagent when available**, supplied only with frozen protocol, diff, fixtures and artifacts; if unavailable, make limitations explicit and perform a structured separate review.
- Freeze code revision, manifest, full run config and scoring criteria after acceptance. The held-out test remains inaccessible in this ticket.

## Hypotheses
- **Engineering hypothesis:** all 100 slots can be completed, validated and replayed under declared budgets without unclassified failure paths.
- **Research (exploratory):** the dev pool provides a smoke test for whether the pipeline measures real variable correctness. Its observed pass@k is **not** the final result and is not a tuning objective.

## Expected outcome
- A completed immutable 100-slot dev ledger with recorded prompts, outputs, extraction traces, scores and retries; missing/ambiguous slots lead to `BLOCKED`, not fabricated completeness.
- Offline reproduction, channel-specific pass@1/2/4 bounds, delta, 95% intervals, latency/quality/diversity summary and limitations.
- One independent review report with critical findings and evidence of any necessary fixes, regression tests and rechecks.
- A frozen pre-test manifest and explicit `READY FOR HELD-OUT TEST` or `BLOCKED` decision.

## Acceptance criteria
- [ ] Offline tests and existing regression suite pass before any live API call.
- [ ] Runtime model, exact numerical T, endpoint, limit policy, hashes, source/dependency revision and split are frozen before the first dev call.
- [ ] Exactly 100 planned dev slots are completed or the run is explicitly `BLOCKED` with missing-slot evidence; all 10×2 treatment pools have n=4.
- [ ] Every completed slot has provenance and oracle status; no ambiguous provider error, missing call or replay mismatch is silently scored.
- [ ] Offline replay reproduces final candidate records and pass@k reports with zero API usage.
- [ ] Review checks sampling independence of slots, native repair fidelity, oracle unknown taxonomy, dataset leakage, statistics and metrics/latency limitations.
- [ ] Critical/blocking findings are resolved with targeted tests and documented in bug register; other observations are recorded without scope creep.
- [ ] Freeze manifest records exact commit and configuration, and a clear final gate verdict. No test calls or test outcome inspection occur.

## Stopping criteria
**STOP as soon as** dev has complete verified results, blocking review findings are closed, and the frozen artifact set supports `READY FOR HELD-OUT TEST`. If rate limits, configuration or ambiguity prevent this within the declared bounded budget, **STOP as `BLOCKED`** with missing evidence. Report the gate status and ask for authorization for Ticket 06; **never start it automatically**. No infinite refinement, parameter sweeps or post-dev “just one more” samples.

## Out of scope
Full 30-case test campaign, conclusions about held-out effect sizes, extra models and revisions made to maximize a dev metric.
