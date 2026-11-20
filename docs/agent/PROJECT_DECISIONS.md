# Project decisions — RQ1

**State:** user-approved research design, 2026-11-20. **Baseline:** original `timur-harin/dualify` commit `7ffd1ae37822096d5b7b573785ee46e877903185`. This file is the human-facing rationale register; see [docs/rq1/SPEC.md](../rq1/SPEC.md) for desired behavior and [docs/rq1/PROTOCOL.md](../rq1/PROTOCOL.md) for authoritative experiment rules.

An **approved** decision may be changed only with a dated amendment stating the reason and affected measures. Such amendments must be approved **before** a held-out evaluation and reflected in both the spec and relevant tickets. Record observations, not retroactive rationalizations.

| ID | Decision | Why this choice (trade-off) |
| --- | --- | --- |
| D01 | Retain original 40 benchmark inputs and conduct a separate leakage/quality audit. | Preserves comparability and prevents opportunistic dataset editing; embedded annotations and weak informal descriptions must be disclosed. |
| D02 | A sampling attempt includes the complete native extractor and repair ladder. | Measures usable final contracts as Dualify produces them; one attempt can cost multiple LLM requests. |
| D03 | Freeze dev/test before experiments. | Protects the later RQ2 methodology from test-data tuning. |
| D04 | Target a group-aware 10/30 dev/test split. | Leaves most cases for reporting while grouping close variants to avoid leakage; 40 tasks limit statistical power. |
| D05 | Use nonzero temperature on initial generation while preserving original repairs. | Encourages candidate diversity without confounding changes to the recovery policy; repairs remain at native T=0. |
| D06 | Report separate spec/code pass@k with latency, error and cost diagnostics. | The channels can fail differently; single merged accuracy would obscure that. |
| D07 | Use an available Qwen model through Groq; pin exact model ID at preflight. | Practical free-tier feasibility matters more than matching the paper's exact model; cross-model claims are out of scope. |
| D08 | Add a single native T=0 baseline per channel/task. | Supplies a reference to original behavior at modest cost; it is descriptive, not an isolated k effect across temperatures. |
| D09 | Main arm: n=4, k={1,2,4}. | Makes a bounded study feasible with Groq Free Tier; limits granularity and power. |
| D10 | Primary metric: combinatorial pass@k. | Estimates coverage from fixed-size candidate pools without privileging arbitrary sample order; first-k is diagnostic. |
| D11 | One model-appropriate positive temperature, fixed before dev. | Focuses RQ1 on candidate count, not temperature tuning. |
| D12 | Count only decisive equivalence as success; show an unknown-sensitive upper bound. | Avoids falsely treating solver unknown as proven wrong while preserving a conservative main measure. |
| D13 | Bounded, cause-based infrastructure retries and same-slot resume. | Separates provider unavailability from model/extractor quality; no resampling-until-valid. |
| D14 | Describe coverage gain and uncertainty, with no arbitrary minimum-effect threshold. | pass@k is nondecreasing by construction, so effect size and expense are more informative than monotonicity. |
| D15 | Limit RQ1 to original p01/p02 and existing gold scoring. | Isolates generation quality; later planning/execution phases are irrelevant to oracle coverage. |
| D16 | Dev engineering gate, freeze, then one held-out test campaign. | Prevents test-set tuning; the test run requires separate approval after dev. |

## Architecture decisions accompanying the approved protocol

**A01 — External orchestration seam (planned).** Prefer a thin RQ1 runner and per-attempt client adapter around the original interfaces over changes to extractors, prompts or Z3. Higher-level integration is easier to test without altering native behavior. Narrow source edits require explicit evidence, scoped tests and a documented justification.

**A02 — Transcript identity (planned).** Each candidate gets a unique attempt slot, ordered LLM call log and output. Strict replay requires exact cardinality, prompt hashes and exhaustion checks. The upstream prompt-matching mode can reuse a previous response and cannot establish independent sampling.

**A03 — Primary analysis unit (planned).** Macro-average by benchmark task, separately for channels, then estimate paired coverage gain and its interval using task/group-aware resampling. Counts and group composition are disclosed because held-out data are small.

**A04 — Source and scope (approved for this documentation branch).** Branch directly from the current original upstream commit in `dinar5150/dualify-thesis`; earlier fork branches are untrusted draft work and are outside the design source. This stage writes *Markdown only* and stops after review. It does not implement code or make live LLM requests.

**A05 — Original Z3 approach is frozen (approved, 2026-11-20).** Preserve upstream solver/checker semantics, 5-second timeout policy, formula fragment, reference contracts and native extraction/repair behavior for the RQ1 experiment. Record original-paper/method bugs and limits in [KNOWN_DUALIFY_LIMITATIONS.md](KNOWN_DUALIFY_LIMITATIONS.md), with evidence and research caveats. Do not repeatedly diagnose recorded baseline behavior or silently fix it. Any change to the original method requires a distinct, explicit methodological approval (and is outside the existing tickets).

## Unresolved run-time configuration (not decisions yet)

- Exact Groq-compatible Qwen **model ID** and whether that model/mode is still available.
- Numeric initial sampling temperature justified by the **actual model** documentation.
- Provider-visible effective request/token quotas and safe throttle/retry budgets.
- Fixed split and bootstrap seeds, actual corpus/duplicate groups, and benchmark-content checksums: produced by Ticket 01 before any live run.

Do not insert guessed values to fill these gaps. Ticket 05 must reject an incomplete run manifest.
