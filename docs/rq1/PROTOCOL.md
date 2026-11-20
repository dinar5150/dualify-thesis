# RQ1 pre-registered evaluation protocol

**Status:** user-approved methodological rules with pending *runtime configuration values*. Follow this document for experiment design; [SPEC.md](SPEC.md) defines the feature, [PROJECT_DECISIONS.md](../../PROJECT_DECISIONS.md) gives rationale, [CONTEXT.md](../../CONTEXT.md) defines terms.  
**No implementation or live experiment is being executed during the documentation-only stage.**

## 1. Fixed source, inputs and leakage audit

- Base implementation: **original upstream** `timur-harin/dualify` at commit `7ffd1ae37822096d5b7b573785ee46e877903185`. A future implementation commit must identify this baseline.
- Work with all **40** original `lifted_auto_eval` input cases and the corresponding **40** `lifted` human-confirmed gold contracts. Inputs and gold are immutable research resources.
- Freeze a manifest of unique benchmark IDs: exactly **10 dev / 30 held-out test**. Detect same/near-same functions using source and identity, keep duplicate groups on one side, and preserve broad provenance/`needs_attention` balance where feasible. Record seed, grouping rule, group membership, IDs and input/gold digests. Never rely only on filenames as group identity.
- Audit **all** original inputs for code-level formal annotations, gold-like literals, weak informal specifications, duplicate source behavior and risky gold metadata. Produce case-level evidence and counts without rewriting or excluding cases after viewing performance.
- No gold precondition/postcondition text is passed to the **extractor** or incorporated in the generation prompt. Test gold remains offline and is consulted only once test candidates are frozen.

## 2. Model and configuration freeze

Before the first dev API call, persist: exact Groq/Qwen model ID, account-visible model availability and mode, API base URL and response format, positive sampling temperature chosen from **applicable model-specific guidance**, baseline temperature=0, repair temperature=0, top-p if set (otherwise record default), token budget, client-side timeout, retry budgets, throttle/rate-limit policy, SDK/dependency versions, source commit, split digest and prompt hashes.

Use one model/endpoint/settings bundle for baseline and sampling, differing only where the protocol explicitly requires temperature. **Do not claim an assumed quota or server timeout applies to every Groq model/account.** A manifest with missing required fields blocks dev.

## 3. Candidate protocol and sample budgets

For each case in the chosen split and each channel:

1. Run one baseline **full original extractor** with temperature 0 for initial generation and native repair.
2. Run **four** treatment attempts, indices 1–4, independently invoking the native full extractor with initial temperature T>0 and native T=0 repair/safe subset.
3. Capture one unique slot `(case_id, channel, arm, sample_index)` and a final extraction for every completed attempt; store stage trace, degradation, actual formula, logical-call ledger, elapsed time and linkage to recorded LLM messages.
4. Preserve repeated generated formulas: **four attempts do not require four unique contracts**. Never use gold, the prior candidate, self-consistency or a selector to inform a later attempt.

The number of full extraction attempts is **10 × 2 × 5 = 100** for a complete dev campaign; **30 × 2 × 5 = 300** for held-out test (future separate authorization); **400** across both. Native repair, API retries and any auxiliary preflight can increase the physical HTTP volume. Number of attempts is *not* number of LLM calls.

The treatment must contain n=4 **completed slot identities** per task/channel; missing slots mean the campaign cannot be reported as a completed pass@k estimate.

## 4. Provider errors and recovery state machine

**Operational states:** planned → running → completed; or running → retriable_infrastructure_failure → retry/resume_same_slot → completed; or running → permanent_config_failure (abort); or running → unresolved_infrastructure_failure (incomplete campaign).

- **Retryable infrastructure (bounded):** connection/network timeout, 429, transient 5xx and similarly evidenced service conditions. Use recorded backoff and finite max attempts; honor provider retry guidance where possible.
- **Permanent configuration:** authentication/permission failure, removed/unavailable model, invalid endpoint, incompatible API parameters, missing key or unsupported capability. Fail fast; no silent model switch or invalid run.
- **Model/extraction failure:** malformed JSON returned by model, unsupported formulas, native validation errors, weak/degraded fallback, and a provider error explicitly due to model-generated output failing structured-output validation (which may have 4xx HTTP status). Do **not** classify merely from status number. Preserve native repair/degradation behavior and count a completed final attempt as an outcome; do not grant free fresh attempts until valid.
- **Ambiguous failures:** retain original status/message, classify on dev and document the decision before test. No silent default to retriable infrastructure.
- **Swallowed errors:** since native extraction may catch exceptions, the wrapper must observe and correlate client failures with the slot. Infrastructure-exhausted degradation is **not** a trustworthy completed candidate. Preserve already successful messages and completed slots on resume. A timeout after request dispatch may not permit byte-identical sampling on retry; record this provenance rather than claiming the original response was recovered.
- **Incomplete slots:** never silently reduce n, insert the last cached response, or convert an absent provider response to a gold failure. Resume within policy or stop with incomplete status.

## 5. Offline transcripts and score integrity

Store append-only logical-request records with exact **slot ID**, call sequence, prompt hash, sampling parameters, provider/model identity, returned JSON or error class, plus final candidate/formula and native extraction trace. Never store API keys.

The original `ReplayLLMClient(match_by_prompt=True)` can reissue its final recorded answer for an exhausted repeated prompt. **For RQ1 use strictly ordered replay plus ledger-level expected slot/call counts and exhaustion checks**, and reject inconsistent prompt hashes, missing records, unexpected additional records and fake candidate identities. Repeated answers from *separate live calls* are legitimate, but replay is a verifier, not a source of extra candidates.

Use existing `score_extraction_against_gold` and original `check_equivalence` semantics/timeout. A negative boolean is not enough to conclude non-equivalence: inspect `reason`, diagnostics and type/parse failures.

Every completed candidate has one adjudicated label:
- `equivalent`: decisively equivalent to original gold in the formal fragment;
- `non_equivalent`: decisive negative/counterexample;
- `invalid`: malformed or unusable candidate, distinct from unknown;
- `inconclusive`: solver `unknown` or another formally unresolved check.

If the current native result does not expose enough information to disambiguate a label, report **unclassified + evidence**, fail the scoring gate and address the observation at the narrowest seam. Never guess.

## 6. Statistical estimands and metric formulas

For a treatment task/channel with n=4 completed candidates, c decisively equivalent and u inconclusive (0 ≤ c+u ≤ 4):

- `low(k) = 1 − C(4−c,k) / C(4,k)` (conservative, confirmed successes only);
- `high(k) = 1 − C(4−c−u,k) / C(4,k)` (unknown sensitivity bound);
- `k ∈ {1,2,4}`. Use `C(a,k)=0` when `a<k`.

Examples:
- c=0,u=0 ⇒ low(1,2,4)=(0,0,0).
- c=1,u=0 ⇒ low(1,2,4)=(0.25,0.50,1.00).
- c=4,u=0 ⇒ all 1.
- c=0,u=1 ⇒ low all 0; high(1,2,4)=(0.25,0.50,1.00).

Compute **per-task** low/high then equal-weight macro-average across tasks independently in **spec** and **code** channels. Primary estimated coverage gain: `delta_4_1 = low(4) − low(1)` within the **treatment**, with the corresponding unknown-sensitive difference reported carefully as a sensitivity analysis (not as an independent estimand). Baseline single-attempt accuracy T=0 is descriptive and should not be subtracted from treatment pass@4 as if only k changed.

Compute 95% paired **group-aware bootstrap** intervals (e.g. fixed-seed cluster resampling by duplicate/source group; report seed, method, number of resamples and effective groups). Re-sample the same cases/groups for pass@1, pass@4 and their *paired* difference; never treat four candidates from one task as independent tasks. The CI is descriptive with n≈30, not a claim of universal model accuracy. Also report first-k observed coverage as a **diagnostic**, not a replacement of the combinatorial estimator.

**Do not test monotonicity as a discovery:** combinatorial pass@k is mathematically nondecreasing in k for a fixed pool. The relevant result is the size of the change, its uncertainty, fraction of mixed-outcome cases (0<c<4), and expense.

## 7. Required diagnostics and latency caveat

**Mandatory, directly observable:**
- candidate-equivalence status and raw reason/diagnostics, c/u per task and channel;
- degraded, weak-postcondition, used-fallback and initial/repair stage distribution;
- unique final formulas / 4 slots and duplicate rate (a diversity proxy, not semantic independence);
- full **extractor attempt elapsed time** with definition and timestamps, total campaign wall-clock time, completed/incomplete slot counts;
- logical LLM calls and effective temperatures where the client adapter can observe them;
- extraction, validation, provider and oracle error counts, including attempted recovery and terminal status;
- baseline success rate, treatment pass@k low/high, delta, 95% uncertainty, first-k diagnostic.

**Conditional on observable telemetry only:** physical HTTP request count (including hidden transport retries and endpoint fallbacks), actual response tokens, Groq inference-only latency, backoff vs compute breakdown. Provide coverage/NA if not instrumented; **do not call attempt elapsed time “pure model inference latency.”** Attempt time may include retries and rate-limit waits. Provider Free Tier quotas and model availability are external confounders, not direct measures of algorithmic quality.

For costs, report number of candidate attempts and observed logical API calls; do not invent a dollar price for a free tier or infer uncaptured token use.

## 8. Artifacts, reviewer checks and freeze

A future complete run should produce:
1. source/config provenance manifest and checksum-verified 10/30 split;
2. leakage audit with case IDs and known limitations;
3. ordered candidate ledger, one row per planned slot, status and immutable IDs;
4. logical request/response transcript and replay verification manifest;
5. per-candidate gold oracle scores with reason, diagnostics and raw statuses;
6. per-task, per-channel pass@1,2,4 low/high and case-level error/recovery diagnostics;
7. macro summary, paired delta and intervals, latency/call/diversity breakdown, missing-telemetry declarations;
8. a testable, credential-free offline reproduction procedure and independent review findings.

**Gate A — offline green:** existing regression suite and RQ1 fake-client/replay tests pass; zero accidental Groq calls; data integrity and pass@k boundary tests pass.

**Gate B — dev complete:** one full 10-case dev run with 100 completed slots, no unexplained ambiguous errors, reproducible offline scores and a review of metric and leakage correctness. Objective defects may be fixed and the dev replayed; document each iteration. No quality-based tuning on held-out cases.

**Gate C — freeze + STOP:** record exact implementation commit, model/config, manifest/split, scorer settings and hashes; verify evidence vs ticket acceptance; explicitly conclude **READY FOR HELD-OUT TEST** or **BLOCKED**. **Stop here**. Do not run a held-out experiment without the user's separate post-dev authorization.

**Gate D — held-out (separately authorized future stage):** one 30-case, 300-attempt test campaign and offline analysis with the frozen configuration. No rescoring policy changes or post-hoc tuning as a response to test outcomes. If corrupted/missing, document the failure and obtain explicit decision before any rerun.

## 9. Threats to validity and disclosures

- n=4, held-out tasks=30, source-group dependence and wide intervals.
- Original gold contracts are fragment-scoped and some cases may be `needs_attention`; invalid/unknown outcomes can make lower/high bounds far apart.
- Original input code may contain formal annotations; this is audited rather than silently stripped. Some informal specs may be generic.
- Model/provider/runtime may drift even when the visible model ID is fixed; provider seed-based bitwise reproducibility is not promised.
- A native full extractor's repair ladder varies its number of LLM requests by candidate; “number of candidates” and actual cost must be reported separately.
- Infra recovery and provider policy can affect elapsed times and observed runs; selection of only valid contracts would inflate coverage.
- No claims about learned selection (RQ2), PEFT (RQ3) or complete program semantics follow from this experiment.
