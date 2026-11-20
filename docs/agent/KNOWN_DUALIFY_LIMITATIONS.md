# Known limitations and reported bugs of original Dualify

**Scope:** the **original article's approach** and original upstream implementation, especially its contract-to-Z3 checking and gold-oracle semantics. This document protects the research baseline from inadvertent modifications and prevents repeated investigations of already recorded limitations.

**Reference revision:** [timur-harin/dualify at `7ffd1ae37822096d5b7b573785ee46e877903185`](https://github.com/timur-harin/dualify/tree/7ffd1ae37822096d5b7b573785ee46e877903185). These facts concern that revision, not older thesis-fork branches.

## Mandatory rules for agents

1. **Consult this register first** whenever an upstream extraction, Z3, formula-fragment, equivalence, or gold-scoring behavior seems wrong. Read the reproduction/evidence before spending time rediscovering it.
2. **Preserve original Z3 semantics for the thesis RQ1 experiment.** Treat the original checker, solver configuration/timeouts, formula parser, equivalence interpretation and reference contracts as **frozen experimental controls**. The RQ1 implementation may observe raw statuses and classify them in reports; it must not silently alter how Z3 proves or refutes formulas.
3. **Record, do not auto-fix:** if a new original-method bug is confirmed, add it here with evidence, its effect on validity and a proposed note for the next supervisor meeting. Prefer documenting/stratifying limitations in the results. A change to the original method requires a distinct, explicitly approved methodological decision and is **out of scope for existing RQ1 tickets**.
4. **Avoid redundant research:** if a behavior is already documented, reuse the diagnosis and cite its ID. Re-investigate only if a newer upstream revision or a concrete contradictory reproduction invalidates the recorded facts; append evidence and date.
5. **Distinguish** verified upstream behavior, suspected flaw, confirmed reproducible bug and accepted research limitation. Never claim a hypothesis or a user-reported issue is reproduced until it is actually verified.
6. **Separate registers:** defects in the *new* RQ1 runner, candidate identity, retry policy and analytics belong in [KNOWN_BUGS.md](KNOWN_BUGS.md). Link to them here when relevant rather than copying descriptions.

## Source-confirmed baseline behaviors (not automatically bugs)

| ID | Status | Evidence in original upstream | Consequence for thesis RQ1 | Required handling |
| --- | --- | --- | --- | --- |
| DUALIFY-LIM-001 | **Verified code behavior; limitation** | `src/dualify/phases/p03_smt_checking.py` fixes a Z3 solver timeout at `_SOLVER_TIMEOUT_MS = 5_000` and checks for `z3.unknown`. | Some equivalence questions can remain undecided within the original time limit. | Keep the timeout and checker unchanged. Report `unknown` separately and use conservative/optimistic pass@k bounds. |
| DUALIFY-LIM-002 | **Verified code behavior; reporting hazard** | The original equivalence result can set `equivalent=False` with reason `solver_unknown` (and distinct well-formedness details). | A false equivalence flag alone does **not** establish decisive non-equivalence. | Preserve `reason`, `well_formedness` and solver diagnostics; classify inconclusive outcomes at the research-report level only. |
| DUALIFY-LIM-003 | **Verified source/data scope; limitation** | `benchmark/lifted/README.md` describes 40 human-confirmed, **in-fragment** reference contracts; gold scoring uses the original checker. | The gold oracle measures equivalence to a **fragment-scoped reference**, not all behavior of the Python function. | State this scope in the thesis; do not strengthen or “correct” gold formulas for RQ1. |
| DUALIFY-LIM-004 | **Verified sample-size limitation** | The source `benchmark/lifted_auto_eval/` and `benchmark/lifted/` each contain the matched 40-case benchmark used by the study. | Small held-out groups and related functions limit statistical power and independence. | Use the approved group-aware 10/30 split, report provenance and confidence intervals, and document limited generalizability. |
| DUALIFY-LIM-005 | **Audit pending; NOT a confirmed bug** | Upstream inputs may contain pre/post-like annotations or brief informal descriptions; precise case-level frequency has not been audited for RQ1. | Baseline prompts may expose formal hints; some tasks may be under-specified by natural language. | Ticket 01 audits every original input without rewriting inputs or filtering on outcomes; report observed limitations afterward. |
| DUALIFY-LIM-006 | **Verified design behavior; not a confirmed bug** | Original p01/p02 include validation, repair/safe-subset logic and degraded final results. | One final candidate can require multiple LLM calls; weak or degraded extraction may be a legitimate failed attempt. | Preserve the full native ladder, report repair/degradation and use **attempt count**, not raw HTTP count, for k. |

**Source links:** [SMT checker](../../src/dualify/phases/p03_smt_checking.py), [gold scorer](../../src/dualify/gold_scoring.py), [benchmark description](../../benchmark/lifted/README.md), [spec extractor](../../src/dualify/phases/p01_spec_to_logic.py), [code extractor](../../src/dualify/phases/p02_code_to_logic.py).

The upstream replay behavior that can reuse prompt-matched answers is an **RQ1 integrity hazard** (see `RQ1-001` in [KNOWN_BUGS.md](KNOWN_BUGS.md)); this is **not** evidence that the published Z3 oracle is buggy.

## Confirmed bugs of the original article/method

**No additional bugs have been supplied or independently reproduced for this register yet.** The user plans to discuss specific bugs at the next supervisor meeting. Add those issues **after** receiving the evidence. Do not infer them from the limitations table or old draft branches.

Use one entry per issue:

### DUALIFY-BUG-NNN — <precise short title>

- **Status:** reported / reproduction pending / reproduced / discussed with supervisor / accepted limitation / approved for separate investigation
- **Origin:** paper claim, original code or benchmark behavior
- **Source revision and affected component:** precise commit and location
- **First reported / last checked:** date
- **Observed behavior:** input, expected result, actual result and raw Z3 reason/diagnostics
- **Minimal reproduction:** commands, fixture, solver version and timeout (if relevant)
- **Why it matters:** which equivalence, gold score, channel or scientific conclusion is affected
- **Evidence:** attached log, test, screenshot, code reference or meeting notes
- **RQ1 handling:** report/stratify/caveat; whether the existing experiment remains valid
- **Decision and owner:** user's/supervisor's decision, date, any follow-up ticket
- **Original Z3 implementation changed?:** **No** under the currently approved RQ1 protocol
- **Re-investigation trigger:** the specific new information that would justify revisiting this issue

## Meeting handoff

Before the next supervisor meeting, compile unresolved **DUALIFY-BUG-NNN** entries as concise evidence-backed questions. After the meeting, capture the user's report and any supervisor decision here. Do not modify the original checker as a substitute for that discussion.

For experimental reporting and pre-registration see [RQ1 protocol](../rq1/PROTOCOL.md) and [project decisions](PROJECT_DECISIONS.md).
