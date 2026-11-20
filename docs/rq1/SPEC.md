# RQ1 approved experiment — implementation contract

**Approved:** 2026-11-20. **Base:** upstream `7ffd1ae37822096d5b7b573785ee46e877903185`. **Stop gate:** after 10-case dev; held-out test explicitly excluded.

## Research target
Question: *How does the chance of generating a correct contract change when the model produces more candidates?* Evaluate **gold-oracle coverage** separately for spec and code; this does not establish reference-free selection accuracy (RQ2).

Primary estimate: for each task/channel, collect `n=4` final candidates, with `c` confirmed-equivalent; calculate `pass@k = 1 - C(4-c,k)/C(4,k)` for k∈{1,2,4}. Average across tasks. Primary effect `Δ = pass@4 - pass@1` inside the same positive-temperature arm. Report one original `T=0` baseline attempt for context (not a matched-temperature causal comparison). For `u` oracle-unknown candidates, report sensitivity upper bound by replacing `c` with `c+u`; invalid candidates do not count as unknown.

## Frozen input
Keep all 40 `benchmark/lifted_auto_eval/*.py` and `benchmark/lifted/*.yaml` unchanged. Deterministic, group-aware 10 dev / 30 test split, stable IDs, corpus/needs_attention audit, SHA256 inputs and gold. Source similarity groups must not cross split. Never use test gold in LLM inputs or development adjustments. Gold is offline scoring only; RQ2 exports are gold-free.

## Candidate generation
Original p01/p02 extraction, identical prompts, validation, repair and postprocessing. Each candidate is one complete extraction, potentially several LLM requests. Intervention initial `generate_json` call uses frozen model-specific T>0; any repair uses original T=0. Baseline uses T=0. Four independent attempt slots per task/channel; identical text outputs remain distinct. No adaptive prompts, feedback, filters or resampling until four valid outputs.

Exact Groq model identifier, positive T, mode, endpoint, quotas, timeout and versions must be documented before first live dev call. A slot has a unique case/channel/arm/index identity and a private transcript. Hash prompt, response, source and configuration. Strict sequential replay must consume precisely all recorded responses, verify temperature and fail on missing/extra calls.

## Failure policy
Network timeouts, 429 and 5xx are bounded infrastructure retries; exhausted faults make slot incomplete even if native extractor swallows the exception. A generated-output JSON validation error, including certain 400/422 responses, is an **extraction failure** subject to normal original repair, not a cost-free resampling opportunity. Bad auth, invalid model ID and configuration errors abort the campaign; ambiguous cases are surfaced, not silently skipped. Resume only interrupted slots and preserve successful transcript prefix.

## Metrics and inference
- Main: spec/code pass@1/2/4 and paired Δ4,1; confirmed lower and oracle-inconclusive upper bounds.
- Bootstrap: paired group resampling, 10,000 iterations, frozen seed and 95% percentile CI. Resample groups with all their member tasks and all k jointly; explain limited sample size.
- Health: completed/invalid/degraded/repair frequency, number of distinct normalized final contracts and duplicate rate; do not deduplicate before pass@k.
- Cost: logical LLM calls, end-to-end extractor latency and offline solver latency (median/p95), error classes, wall-clock duration. Only report physical retries/token usage/server inference time when observed; otherwise explicitly `not_measured`. Groq Free tier rate-limiting is not LLM inference latency.
- Candidate pools must be scoreable entirely offline, repeatably, with separate gold-free data ready for future RQ2.

## Ready for held-out test (STOP, do not execute)
1. Immutable split/audit and locked config with checksums.
2. Fake-client offline tests: temperature/repair parity, original T=0 parity, 400 JSON-format failure vs 429/network/5xx and config failures, strict replay and interrupted-slot resume, n=4 denominator integrity.
3. Existing `ruff`, `mypy`, and `pytest` pass. New pass@k/unknown/bootstrap and report tests pass.
4. Execute **only 100 dev slots** (10 tasks × 2 channels × (1 baseline + 4 sampled)), or stop with accurately recorded incomplete status if API unavailable.
5. Dev candidates replay to identical offline gold report; independent standards/spec review completed with blockers fixed.
6. Freeze code/config/transcripts, write outcome in [STATUS.md](STATUS.md), and **stop**. Test 30×2×5 requires distinct explicit authorization.

## Non-goals
RQ2 selector design, RQ3 fine-tuning, gold modification, prompt engineering, change to Z3/formula language or p03–p05, benchmark cleaning, temperature/model search, new k values, unbounded retries, test-driven tuning.
