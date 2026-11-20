# Project decisions — thesis RQ1

**Status:** Accepted by researcher, 2026-11-20. Source: 16-round-question interview and approved Research Specification v0.1. **Only an explicit amendment changes the experiment.**

| ID | Decision | Why; rejected alternative |
|---|---|---|
| D01 | Preserve the original 40-case benchmark and separately audit leakage | Comparability beats retroactively cleaning difficult inputs. |
| D02 | One candidate is the full original p01/p02 extractor with repair | Matches deployed Dualify; raw response is an intermediate stage. |
| D03 | Freeze a group-aware 10-dev / 30-test split first | Prevent test-led tuning and duplicated function spillover. |
| D04 | Nonzero temperature only for initial sampling, native T=0 for repair | Isolates candidate diversity while holding the correction procedure fixed. |
| D05 | Separate spec and code pass@k | Different information channels may have different quality. |
| D06 | One available Qwen model served by Groq; exact model ID frozen | The thesis tests inference-time sampling, not one model's leaderboard standing. |
| D07 | A single original T=0 baseline attempt per channel/task | Provides an original-behavior reference without doubling the experimental series. |
| D08 | n=4 and k=1,2,4 | Bounded budget for free-rate-limited inference. |
| D09 | Chen-style combinatorial pass@k; primary Δ(pass@4 - pass@1) | Coverage probability rather than arbitrary first-k ordering or selector accuracy. |
| D10 | One justified fixed positive T, not temperature search | Avoid confounding the k-study with hyperparameter optimization. |
| D11 | Confirmed-equivalent lower bound plus oracle-unknown upper bound | UNKNOWN does not prove wrongness; invalid syntax is not UNKNOWN. |
| D12 | Classify Groq infrastructure faults and resume the same slot | Retried network/rate-limit errors are different from model/repair failures. |
| D13 | Descriptive estimation with confidence intervals, no post-hoc win threshold | Small held-out sample and mechanically nondecreasing pass@k. |
| D14 | Reuse original p01/p02 + `gold_scoring`; exclude p04/p05 | Keep experimental treatment minimal and reproducible. |
| D15 | Strict holdout and dev-only readiness gate | Reserve 30 held-out tasks for separately authorized evaluation. |
| D16 | Keep physically observed HTTP counts separate from logical model calls | Native client retries internally; never report unobserved provider timings as inference speed. |

## Amendments and provenance
- Base commit (upstream `main` at branch creation): `7ffd1ae37822096d5b7b573785ee46e877903185`.
- The researcher authorized implementation and files in a **new branch in `dinar5150/dualify-thesis`**, with no reuse of old thesis branches.
- Preserve precise rationale and technical edge cases in [docs/rq1/SPEC.md](docs/rq1/SPEC.md); do not duplicate that entire document here.
- No additional experiment variants, solver changes, model selection on test, or held-out sampling are authorized.
