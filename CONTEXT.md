# RQ1 domain glossary

- **Thesis RQ1** — changes in the chance of obtaining at least one *gold-equivalent* contract as the number of sampled candidates increases. Distinct from the original Dualify **paper RQ1** (cross-channel agreement).
- **Benchmark case** — one unique `benchmark_id` with immutable source and gold-reference provenance. Multiple functions can have similar names, so identity is not the short function name.
- **Channel** — `spec` (original p01 extracts from informal specification) or `code` (original p02 extracts from function source).
- **Attempt slot** — one scheduled, uniquely identified invocation of the **complete original extractor**, including possible repair and salvage. Infrastructure failures can leave it incomplete.
- **Candidate** — one final `ExtractionResult` from one completed attempt, including preconditions and postcondition; not one HTTP request or one intermediate LLM response.
- **Repair ladder** — original Dualify sequence of validation, repair, safe-subset repair and fallbacks. It stays identical between arms.
- **Baseline arm** — exactly one complete attempt per case/channel, with initial sampling at temperature zero.
- **Sampling arm** — four complete independently executed attempt slots per case/channel; initial generation at frozen nonzero temperature, repair at native zero.
- **Gold oracle** — original `gold_scoring` and Z3 equivalence checker applied **offline** to frozen final candidate contracts.
- **Confirmed success** — decisively equivalent to the reference contract within Dualify's supported verification fragment.
- **Oracle inconclusive** — Z3 UNKNOWN or another unresolved formal judgment; counted as an unknown in sensitivity bounds, not proved incorrect.
- **pass@k** — combinatorial estimate of oracle coverage for k sampled candidates out of the four frozen attempts; not a selector's accuracy or online first-k outcome.
- **Leakage audit** — inventory of annotations, generic specs, reused functions and possible reference information visible in original inputs; inputs themselves remain unchanged.
- **Dev/test holdout** — group-aware frozen 10/30 split; dev supports engineering validation, test is reserved for one later authorized evaluation.
