# 02 — Produce one native extraction attempt with observable temperature and failure provenance

**Status:** ready-for-agent (NOT STARTED)  
**Blocked by:** [01 — Benchmark split and audit](01-benchmark-split-and-audit.md).  
**Deliverable:** A single offline-verifiable full extractor attempt on each channel, preserving original validation and repair, with correct temperature routing and observable terminal status.

## Problem
The original p01/p02 extractors delegate initial generation and repairs through the same LLM client interface and default to temperature 0. Sampling temperature must vary **only** for the first generation call, without changing original prompts or recovery behavior. Meanwhile an extractor may swallow a provider exception and return a degraded result, hiding a failed infrastructure slot from evaluation.

## Known facts
- Original `LLMClient.generate_json(prompt, temperature=0.0)` supports an explicit temperature argument, but p01/p02 initial and repair calls normally rely on the default.
- Both p01 and p02 perform validation, optional repair/safe-subset and degraded recovery; a full attempt can make multiple logical model calls.
- Original OpenAI-compatible client may retry requests and attempt a different completion endpoint. Network-level attempts are not identical to logical LLM calls.
- The approved study keeps the original repair ladder and T=0 repair behavior while giving the first treatment generation one fixed T>0.
- A malformed model-generated JSON response is not automatically a recoverable infrastructure event.

## Constraints
- Integrate at the **highest safe client/orchestration seam**; preserve original extractor signatures/prompts/formal semantics unless a narrowly evidenced technical reason forces a change.
- Treat one **complete** extractor invocation as one candidate attempt, even when the resulting postcondition is weak or degraded.
- Baseline initial and repair = T=0; treatment **initial** = frozen T>0, every native repair = T=0. Reset adapter state for every new attempt.
- Classify transport/rate-limit/5xx, permanent config/auth/model failure, model-format failure, inconclusive and ambiguous response by evidence. Preserve original errors and context rather than guessing from HTTP status alone.
- Retry only retriable infrastructure failures with finite, logged policy; do not provide free fresh samples for invalid JSON/formulas. If an outage is swallowed into degraded output, recognize an incomplete slot.
- Keep model credentials out of logs. Use fake clients for all tests. Avoid touching Z3/p03–p05.

## Hypotheses
- **Engineering hypothesis:** a per-attempt client boundary can observe and route the initial/repair calls without modifying the original repair ladder, while propagating sufficient failure provenance for truthful slot accounting.
- If the original interface cannot expose a classification, document exactly what is unobservable and propose the smallest tested seam change rather than inventing telemetry.

## Expected outcome
- One complete spec-channel and one complete code-channel example produced from fake model responses, with explicit T-routing, unchanged native extraction behavior and stage trace.
- A normalized attempt record containing slot ID, model/settings, final extraction, temperature sequence, logical-call count, elapsed time and error/evidence category.
- Tests demonstrating successful initial extraction, native repair, degraded extraction, bounded retriable outage, non-retriable config failure and output-format failure as a model/extraction outcome.

## Acceptance criteria
- [ ] A fake-client integration check shows **T>0 once on treatment initial generation** and T=0 on all subsequent native repairs, for both channels.
- [ ] A T=0 baseline goes through exactly the native full extractor, preserving final content and trace under the same fake responses.
- [ ] A returned invalid/degraded extraction remains a completed candidate when caused by model/extraction behavior, not an extra resampling opportunity.
- [ ] A swallowed, exhausted infrastructure error is surfaced as incomplete rather than scored as an incorrect candidate.
- [ ] Authentication, unsupported model/endpoint and permanent configuration errors stop with evidence; transient retries are bounded and logged.
- [ ] Tests cover output-validation error reports that have HTTP 4xx status without incorrectly treating them as ordinary outages.
- [ ] Existing regression tests still pass; no Groq request is required to demonstrate the ticket.

## Stopping criteria
**STOP when:** both channels pass the observable full-attempt, temperature-routing and failure-taxonomy tests; the existing test suite remains green; and the attempt record has a reproducible example. If the adapter seam cannot preserve the native extractor behavior, mark the ticket `BLOCKED` with a minimal reproduction and proposed change. Do not build four-candidate pools, run a live model, or polish unrelated modules.

## Out of scope
Sampling n=4, final pass@k analysis, live dev/test campaigns and rewriting original native repair.
