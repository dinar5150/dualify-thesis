# Domain glossary — Dualify thesis RQ1

This is the **ubiquitous language**, not an implementation plan. Use these terms consistently in specs, tickets and reports.

| Term | Meaning |
| --- | --- |
| **Benchmark case / task** | One original Dualify example with a unique benchmark identifier, source code, informal specification and linked human-confirmed gold contract. |
| **Spec channel** | Generating a contract from the informal natural-language specification (original p01). |
| **Code channel** | Generating a contract from the program source (original p02). |
| **Contract** | Formal preconditions/domain constraints and a postcondition in Dualify's supported SMT-checkable fragment. |
| **Gold contract** | A human-confirmed reference for the **supported fragment**, not a complete proof of Python semantics. |
| **Extraction attempt** | One invocation of the **complete original extractor**, including validation, native repair/safe-subset procedures and final postprocessing. An attempt can make multiple LLM calls. |
| **Candidate** | The final contract/extraction result of one completed extraction attempt. A degraded or invalid result is still a candidate, not a reason to sample for free. |
| **Attempt slot** | Preassigned unique task × channel × arm × sample-index unit. It is completed by one final extraction or marked incomplete after unresolved infrastructure problems. |
| **Candidate pool** | The four recorded attempt slots for a task and channel in the nonzero-temperature sampling arm. |
| **Baseline** | A separate, single native extraction attempt with initial temperature 0. |
| **Repair ladder** | Existing sequence of validation, repair, safe subset recovery or degradation undertaken by the original extractor. It is part of an attempt. |
| **Gold equivalence** | A **decisive** equivalence result from existing gold scoring using the original solver semantics. It measures agreement with the reference in the formal fragment. |
| **Non-equivalence** | A decisive negative oracle result; differs from inconclusive solver status. |
| **Oracle unknown** | Z3 or checking outcome that does not establish equivalence or non-equivalence. Do not label as proven incorrect. |
| **Invalid candidate** | A completed extraction that cannot be scored as a well-formed contract; it is not automatically oracle-unknown. |
| **Infrastructure failure** | Unresolved transport/rate-limit/server condition preventing trustworthy completion of a preassigned slot, distinct from a model output error. |
| **Provider attempt** | One physical HTTP attempt; multiple may occur during a logical LLM call or extraction attempt. |
| **Transcript** | Ordered record of LLM prompts, settings and responses used to replay extraction *offline*. Replaying is not new sampling. |
| **pass@k** | Estimated probability of finding at least one confirmed gold-equivalent contract among k samples from a pool of n independently obtained extraction attempts. |
| **Coverage gain (delta_4_1)** | Within-sampling-arm pass@4 minus pass@1, separately for the spec and code channels. |
| **Dev set** | Ten frozen benchmark tasks available for engineering validation. |
| **Held-out test set** | Thirty frozen benchmark tasks evaluated once after the dev gate and explicit approval; no tuning from its results. |
| **Freeze** | Persisted code revision, split, model ID, sampling settings, oracle versions and evaluation rules before held-out test. |
