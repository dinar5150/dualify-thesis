# Thesis RQ1 — Research / Engineering Specification

**Status:** APPROVED research design (interview decisions Q1–Q16, 2026-11-20); documentation-only handoff. **Implementation status:** not started.  
**Source:** [original upstream Dualify](https://github.com/timur-harin/dualify) at `7ffd1ae37822096d5b7b573785ee46e877903185`.  
**Derived from:** the user-approved Research Specification v0.1, thesis RQ1 and original Dualify system paper.  
**Scope:** RQ1 generation and gold oracle only. Experimental rules are defined in [PROTOCOL.md](PROTOCOL.md).

## Problem Statement

The thesis asks: **“How does the chance of generating a correct contract change when the model produces more candidates?”** Original Dualify independently extracts SMT-checkable contracts from an informal specification (p01) and source code (p02). It also offers a human-confirmed gold benchmark and gold scoring, but the standard pipeline does not directly produce immutable four-candidate pools per task/channel with a defensible pass@k, uncertainty and cost analysis.

A single extraction can be wrong, degraded, repeated, or formally undecidable. A simple loop over the model is not sufficient: it can bias results if repairs are altered, infrastructure failures are counted as model errors, replay repeats a cached candidate, gold leaks into prompts, or test examples guide development.

**Scientific meaning:** gold equivalence is relative to the original benchmark's supported formal fragment, not a proof of complete program correctness. The thesis RQ1 is distinct from RQ1 in the original Dualify paper.

## Solution

Provide a **thin research orchestration layer** around original p01/p02 and original gold scoring. For each frozen benchmark task and channel: generate one native T=0 baseline; obtain four separately recorded full extraction attempts with fixed positive temperature on **initial generation only** and native T=0 repair; score final contracts offline; and report combinatorial pass@1, pass@2, pass@4, conservative/unknown bounds, paired coverage gain, uncertainty, diversity and costs. Carry existing extraction traces, solver explanations and provider-failure provenance into auditable artifacts.

Before any live model call, freeze a group-aware 10-dev/30-test split, audit reference leakage and confirm model/configuration. Build mock-first tests and strict offline replay. Complete **one dev verification stage**, freeze implementation/configuration, **stop** and request a separate authorization before held-out test execution.

## User Stories

1. As a thesis researcher, I want the study to use the original Dualify benchmark inputs, so I can compare results without silently changing the research task.
2. As a thesis researcher, I want a frozen 10-dev/30-test split grouped by similar source functions, so test variants do not leak through development.
3. As a reviewer, I want a case-level audit of embedded contracts, weak descriptions and duplicate functions, so I can assess threats to validity.
4. As an experiment operator, I want model ID, endpoint, temperature, corpus checksums and source revision captured before running, so each result is attributable to one configuration.
5. As a researcher, I want a native T=0 baseline on each channel, so I can describe original Dualify's single-attempt behavior.
6. As a researcher, I want four positive-temperature *initial* generations per task/channel, so I can measure candidate coverage at k=1,2,4.
7. As a maintainer, I want native repairs and validation unchanged, so a completed candidate means what it meant in upstream Dualify.
8. As a researcher, I want every attempt slot to have an identity independent of text equality, so naturally repeated outputs are counted but replayed cached outputs are not fabricated as new samples.
9. As a researcher, I want all extraction stages and degradation reasons recorded, so failures are interpretable rather than just false correctness bits.
10. As an operator, I want bounded and classified provider recovery, so 429/network/5xx do not silently pollute candidate quality metrics.
11. As an operator, I want invalid JSON and wrong formulas handled as extraction outcomes, so the experiment cannot resample until it gets valid answers.
12. As a reviewer, I want offline replay to fail closed on missing or extra calls, so I can detect prompt drift and transcript corruption.
13. As a reviewer, I want to recompute gold scores without Groq credentials, so the results are inspectable after a model/provider change.
14. As a researcher, I want confirmed correct, decisively incorrect, invalid and inconclusive oracle results distinguished, so Z3 unknown is not mislabeled a proof of error.
15. As a researcher, I want separate macro-averaged spec and code pass@k, so the two extraction channels can be analyzed fairly.
16. As a researcher, I want unknown-sensitive bounds and paired uncertainty for delta_4_1, so I do not overclaim on 30 held-out cases.
17. As a researcher, I want latency, provider call counts when observable, degradation and diversity diagnostics, so improvements can be weighed against cost.
18. As an AI coding agent, I want one independently testable ticket and a sharp stopping criterion, so I can finish work without uncontrolled polishing.
19. As a maintainer, I want observed defects recorded with reproduction and resolution evidence, so later agents do not rediscover or silently mask them.
20. As a supervisor, I want an explicit dev freeze and a gate before held-out test, so the study does not turn test data into tuning data.
21. As a later RQ2 researcher, I want immutable candidate IDs and gold-free production artifacts, so selection experiments can reuse inputs without reference leakage.

## Implementation Decisions

1. **Integration seam:** orchestrate original extraction and existing gold-scoring interfaces at the highest practical level. Prefer a research-only client adapter scoped to one extraction attempt over modifying p01/p02 themselves.
2. **Channel isolation:** spec and code extraction remain independent. The RQ1 runner must not use agreement between channels or gold truth to generate/revise a candidate.
3. **Stable full-attempt semantics:** candidate = one final native extractor result, including any original repairs, normalization, degradation and postprocessing. Do not define k as raw HTTP calls.
4. **Sampling policy:** baseline is one native T=0 attempt; treatment is four numbered attempts with the same frozen positive temperature on initial generation. Repair retains the original T=0 default.
5. **Pool integrity:** completed pools contain exactly four distinct *slot identities* per case/channel; contract text may repeat naturally. A missing slot makes the corresponding campaign incomplete, not a smaller n.
6. **Limited recovery:** preserve already completed slots; retry infrastructure faults at the same slot within declared limits. Authentication, incorrect endpoint/model and invalid configuration cause preflight/run failure. Model-output errors follow native extractor behavior.
7. **Golden oracle:** reuse native gold equivalence/checking, including its solver timeouts and supported formula fragment. Do not patch Z3 into returning success or replace the oracle with model judgment.
8. **Explicit scoring states:** distinguish confirmed equivalent, decisive non-equivalent, invalid and inconclusive checking. Compute sensitivity bounds when oracle knowledge is incomplete.
9. **Transcript fidelity:** record ordered LLM requests/responses, settings and extraction traces with slot IDs. Strict replay must check ordering, prompt hashes, expected call count and exhaustion. Cached-response reuse is **not** independent sampling.
10. **Immutable data boundary:** snapshot a group-aware manifest containing 40 case IDs, split assignment, provenance and benchmark hashes. No benchmark rewriting or gold injection is allowed.
11. **Statistical design:** macro-average per case; estimate pass@k from n=4, paired delta_4_1, first-k diagnostics and a 95% task/group-aware bootstrap interval with reproducible seed.
12. **Telemetry honesty:** require extractor attempt elapsed time, logical calls if observable, native stage/repair counts, outcome statuses and total campaign wall time. Physical HTTP retries and pure provider inference latency are reported only where directly observable; never infer one from another.
13. **Safe outputs:** run manifest/config, candidate ledger, ordered transcript, offline scores and final aggregates must be mutually cross-checkable. Never publish keys; handle raw prompts/outputs as research artifacts, not agent instructions.
14. **Stage gating:** implement and test without API calls first, run an explicitly authorized full dev study, repair objective bugs using dev only, review independently, freeze, and stop. Held-out test is a later separately approved stage.
15. **Change discipline:** no unrelated refactors, no silent addition of extra generation attempts, no LLM-based selection, no change to the original task texts, and no borrowing implementations from prior fork branches.

## Testing Decisions

Tests should assert **observable behavior at the outermost useful seam**, not the private call graph. Use fake/replay clients and small synthetic records to test the full attempt → ledger → oracle/report route where practical; add focused unit tests only for mathematical boundary cases and failure classification.

**Required automated checks:**
- Deterministic split manifest with complete, non-overlapping 10/30 assignments, group isolation and checksums; audit is stable.
- An initial sampling call uses chosen T>0; original repairs continue at T=0; baseline always uses T=0; source extraction semantics and existing tests remain intact.
- Recoverable provider fault preserves the slot and records bounded retries; invalid model output counts as a candidate via native repair; config/auth fail fast.
- A degraded but completed result counts as one candidate; genuinely duplicated outputs from separate calls keep separate IDs; a missing call or reused cached response cannot fill a slot.
- Strict replay verifies exact ordered prompts, slot membership, completion and transcript exhaustion; replay/scoring perform **zero** outbound model calls.
- Gold-equivalence classification preserves unknown versus negative/invalid and uses the original solver behavior.
- n=4 estimator: c=0 gives all zero, c=1 gives pass@1=.25, pass@2=.5, pass@4=1; c=4 gives all one; unresolved u produces an honest upper bound.
- Channel macro-average, paired delta, first-k diagnostic, group bootstrap determinism, and latency summaries are tested on tiny fixtures.
- RQ1 artifacts reproduce the same offline scores; no test item is ever accessed during dev-stage model calls.

**Existing prior art:** upstream extractor tests, gold-scoring tests, transcript tests, formula/solver-quality tests and reproducibility scripts. Preserve existing checks as regression coverage.

**Review:** once implementation is authorized, an independent reviewer/subagent (if available) audits leakage, sample identity, retry taxonomy, math and freeze boundaries. Its findings must be resolved only if they break the explicit criteria, then rechecked. Review is not permission for endless optimization.

## Out of Scope

- Thesis RQ2 selection without gold, RQ3 fine-tuning, self-refinement feedback across candidates, new SMT semantics, grammar constrained decoding, retrieval prompting, model comparison and temperature search.
- Original action planning/execution and end-to-end p03–p05 action workflow beyond native scoring.
- Full Python semantic equivalence beyond the original benchmark's supported fragment.
- Retroactive modifications of the benchmark/test split based on test outcomes, importing work from old draft branches, or merging unrelated refactors.
- Performing any source implementation or live Groq experiment as part of this **documentation-only** handoff.
- Running the held-out 30-task campaign without a separate post-dev authorization.

## Further Notes

**Primary analysis:** within one fixed-temperature arm, measure delta_4_1 = pass@4 − pass@1 for spec and code separately. The combinatorial estimator cannot decrease with k by construction; the study describes *how much* coverage increases and at what cost, not whether monotonicity is possible. A native T=0 single attempt is a descriptive baseline, not a controlled comparison of k at equal temperature.

**Small sample:** with n=4 and only 30 held-out tasks, pass@4 is binary per task and confidence intervals may be wide. Report coverage gains as estimates with caveats, not universal model properties.

**Definition of Done for the implementation phase:** every accepted dev-stage criterion in [PROTOCOL.md](PROTOCOL.md) passes; the frozen manifest, offline tests, complete dev results, metrics, leak audit, bug register and review report exist; the agent then **stops at READY FOR HELD-OUT TEST**, without running that test.

**Work breakdown:** six files in [tickets/](tickets/README.md). Each ticket is a verifiable vertical slice with independent stopping criteria. The held-out ticket remains gated.

**Open runtime facts:** exact Groq Qwen model ID, model-mode recommendation for T>0 and actual rate limits must be confirmed and frozen at preflight; they are not hardcoded by this document.
