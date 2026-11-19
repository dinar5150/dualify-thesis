# RQ1 technical debt

These observations concern the exploratory pilot and do not justify changes to the
original scorer or extraction protocol. Preserve any existing run and use a new,
explicitly versioned protocol for changes that affect results.

| Issue | Severity | Origin and status | Evidence and impact | Reason deferred |
|---|---|---|---|---|
| Tuple annotation signature parsing | Medium | Original Dualify, confirmed | `_extract_signature_args('swap(things: Tuple[int, int]) -> Tuple[int, int]')` produces `['things', 'int]']`, although the function has one argument. Validation and repairs can be affected. | Changing the original extractor breaks comparability. |
| Heterogeneous tuple encoding | Medium | Original Dualify/Z3 translation, confirmed limitation | A heterogeneous tuple such as `Tuple[int, int, str]` cannot be faithfully represented by the original homogeneous sequence representation; `parse_input` is a diagnostic case. | A new encoding would change the original scorer. |
| Solver unknown | Medium | Original solver configuration, observed limitation | Strings, sequences and quantifiers can be inconclusive at the fixed timeout. Unknown is not a proven failure or a Z3 bug. | The original solver semantics and timeout are frozen. |
| Restricted Python evaluation | Medium | Original Dualify, suspected security risk | The SMT layer uses restricted `eval` on formula text; restrictions alone do not prove an exploit. The solver timeout does not bound all Python parsing/evaluation. | Security and resource isolation require separately scoped work. |
| Provider endpoint fallback and missing traces | Medium | Original provider, confirmed limitation | The client tries multiple endpoint modes and may hide recovered parsing exceptions; interrupted requests can lose telemetry. HTTP errors observable by the wrapper remain recorded. | Altering provider behavior would change the frozen pipeline. |
| Cross-channel source overlap | Medium | Benchmark methodology, confirmed limitation | Some source docstrings contain specification-like text. This limits independence of information sources; it does not establish gold leakage. | Inputs are protected benchmark material. |
| Interruption during atomic publication | Low | RQ1 implementation, confirmed | A process killed during `_write_new` can leave a `.tmp` file, causing resume to stop for manual inspection, even if a result was published. | Rare interruption boundary; preserve the file as evidence instead of automatically deleting it. |
| Hosted model and token usage | Medium | Provider, suspected or observed limitation | A model ID does not pin provider-side weights or ensure statistically independent responses; token usage can be incomplete. Timing excludes interrupted work. | Not controllable by this prototype; report unavailable data. |
| Baseline temperature | Medium | Research methodology, confirmed | Original single-run baseline uses 0.0; the pilot uses 0.7 initially and 0.0 for repair. Differences cannot be ascribed solely to sample count. | The user-approved pilot configuration is fixed. |
| Subset representativeness | Medium | Research methodology, confirmed | Six diagnostic cases do not represent the 40-task benchmark. Unknowns and failures reduce proven-success estimates. | The requested deliverable is exploratory and does not require the full benchmark. |
