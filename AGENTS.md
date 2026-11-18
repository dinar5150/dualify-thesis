# AGENTS.md — Dualify thesis fork

## Purpose and authority

This repository is a research fork of [Dualify](https://github.com/timur-harin/dualify), used for a bachelor's thesis on **improving the accuracy of formal program specification generation at LLM inference time**.

The thesis experiments study contracts extracted independently from (1) informal requirements and (2) Python source code. Dualify translates them into preconditions and postconditions, then uses Z3 to compare formulas. A human-confirmed gold contract is an **evaluation oracle**, not information available to the generator or selector.

**Priority when instructions conflict:** safety and integrity of already recorded experiments > an explicitly approved research protocol > the current user task > repository conventions > optional skill workflows. If a requested change would invalidate comparability, explain the impact and get approval for a separately versioned protocol before editing.

The thesis research questions below are **not** the numbered RQs in the upstream Dualify paper/README:

- **Thesis RQ1 — Generation:** How does the chance of producing a gold-equivalent contract change as the number of independently generated candidates increases?
- **Thesis RQ2 — Selection:** Can comparisons between candidates from requirements and code improve selection accuracy **without consulting gold during selection**?
- **Thesis RQ3 — PEFT (conditional):** Does parameter-efficient fine-tuning improve the chance of generating correct contracts compared with the unchanged model? Do this only if a defensible training/evaluation split is available.

Focus first on RQ1 and RQ2. Do not introduce agentic generation pipelines, training, or additional research methods unless requested.

## Repository orientation

Read the relevant code and documentation before editing; do not guess interfaces from file names.

| Location | Responsibility |
| --- | --- |
| `src/dualify/phases/p01_spec_to_logic.py` | Requirement-to-contract extraction and repair |
| `src/dualify/phases/p02_code_to_logic.py` | Code-to-contract extraction and repair |
| `src/dualify/phases/p03_smt_checking.py` | Z3 translation, comparison, witnesses, solver statuses |
| `src/dualify/phases/p04_action_planning.py` and `p05_action_execution.py` | Original downstream planning/execution; not necessary for RQ1 sampling |
| `src/dualify/gold_scoring.py` | Original reference-based evaluation |
| `src/dualify/runner.py` | Original Dualify baseline |
| `src/dualify/rq1*.py` | Thesis RQ1 sampling, storage, evaluation, analysis, and diagnostics |
| `scripts/run_rq1.py` | Experiment plan and live generation |
| `scripts/evaluate_rq1.py`, `analyze_rq1.py`, `diagnose_rq1.py` | Offline reports |
| `scripts/KAGGLE_RQ1.md`, `scripts/RQ1_FINAL_REVIEW.md` | Kaggle procedure, frozen protocol, and known limitations |
| `benchmark/lifted_auto_eval/` | **40 original benchmark inputs** for thesis RQ1/RQ2 |
| `benchmark/lifted/` | **40 human-confirmed gold YAML contracts** |
| `tests/` | Offline regression and experiment tests |

The upstream baseline reference is commit `7ffd1ae37822096d5b7b573785ee46e877903185`. The initial thesis RQ1 implementation was pinned at `33cd7032e3dec27e47ecb28c611da1b79863da95`. These identifiers are provenance markers, **not** instructions to reset or overwrite the current branch. Check `git status`, `git log`, and the experiment manifest before acting.

## Non-negotiable research invariants

1. **Never alter the original 40 benchmark tasks or gold YAML files to make results look better or tests pass.** The six-case dev mode selects existing benchmark IDs; it is not a replacement research dataset.
2. **No gold leakage.** Never add gold formulas, gold-derived hints, or reference scores to generation prompts, repair prompts, RQ2 ranking features, or selection logic. Apply the gold scorer only **after** candidates are generated or a candidate is selected. Do not tune RQ2 selection rules against final test-set gold outcomes without an explicitly approved evaluation design.
3. **Keep the original Dualify comparable.** Do not silently change original prompts, the repair ladder, fallback rules, parsing/normalization, SMT encoding, Z3 timeout/settings, equivalence semantics, or gold-scoring logic. A necessary fix must be separately scoped, tested, versioned, and reported; never rewrite past experimental results.
4. **Keep source channels distinct.** Requirement-to-contract and code-to-contract generations must use their intended inputs, with no prior candidates or gold feedback. Existing source docstrings may contain specification-like text: record this as a channel-independence limitation, not proof of leakage.
5. **Preserve evidence.** Do not delete, edit, merge, or fabricate persisted attempts, transcripts, manifests, error logs, and original baseline artifacts. Do not silently change failed or inconclusive outcomes into successes.
6. **Do not start paid or long-running LLM/Kaggle experiments without an explicit request.** Prefer offline fixtures, mocks, and `--dry-run` for development. Never commit credentials or print API keys.

## RQ1 protocol and reporting

The current planned full RQ1 run uses **40 tasks × 2 channels × 8 slots = 640 extraction attempts**, with separate spec and code results. The configured Groq model is `qwen/qwen3.8-27b`, initial sampling temperature **0.7**, and original repair temperature **0.0**; the original single-run baseline used temperature **0.0**. Do not attribute a baseline-to-RQ1 difference solely to repeated sampling when temperatures differ.

- A candidate is one **independent** invocation of the original extraction pipeline, including its existing validation and repair. Do not reuse a cached response as a new independent candidate.
- Full runs must preserve exact manifest compatibility (commit, source/input hash, model, temperatures, benchmark IDs, environment, and solver version). Use a new output directory for a changed protocol. Resume existing runs **only with the commit and configuration recorded in their manifest**.
- Each slot has an explicit terminal completed/error outcome or remains unfinished. Preserve API errors (including Groq HTTP 400/404/429), retries when observable, degraded flags, fallbacks, and missing telemetry. A terminal failed generation is not a successful candidate; an interrupted slot is not terminal.
- Primary accuracy is **proven logical equivalence to gold within the supported DSL**, using Dualify's original scorer. `solver_unknown` is inconclusive, not equivalent and not proof of a Z3 defect. Stronger, weaker, incomparable, invalid, and unscorable results must remain distinguishable.
- `degraded=True` does **not** automatically mean incorrect; `ret == ret` and cross-channel agreement do **not** establish correctness. A built-in fallback does not count as model-generated success.
- For RQ1, report separate spec/code, task-macro **pass@k** for `k = 1, 2, 4, 8` using `1 - C(n-c, k) / C(n, k)`. Do not publish a complete `n=8` estimate for a task missing any of its eight terminal slots. The scientific aggregate requires all 40 tasks; dev/partial summaries are exploratory.
- Also report initial/final validity, repair success, proven relation/unknown/error distribution, syntactic uniqueness, elapsed time, API failures, and observable token/call usage. Mark missing measurements unavailable; do not invent monetary cost or missing token counts.
- RQ2 selectors may use requirements, source code, generated candidates, and Z3 comparisons. **Freeze the selection decision before gold evaluation**. Compare against simple selection baselines and report oracle coverage separately from actual selection accuracy.
- RQ3 needs an independently justified, leakage-free training setup and an unchanged-model comparison. Do not train on the 40 final evaluation gold contracts.

## Safe engineering workflow

1. **Inspect first:** read relevant modules, neighboring tests, git state, `scripts/RQ1_FINAL_REVIEW.md`, and existing manifests/artifacts before proposing edits. Do not assume the currently running Kaggle version matches branch HEAD.
2. **Define the smallest change:** for nontrivial work, state scope, affected files, research impact, and verification plan. Ask before changing methodology, baseline behavior, or an active run's protocol; otherwise proceed with reasonable assumptions.
3. **Test-driven, incremental changes:** write an offline regression test that reproduces the bug or specifies the intended behavior; verify it fails, implement the minimal fix, and verify it passes. Prefer small, focused commits over broad refactoring.
4. **Keep data and logic separate:** sampling produces immutable candidate records; evaluation and analysis consume saved records without generating new LLM outputs. Avoid hidden network calls in tests and evaluation.
5. **Check safety:** generated formulas are untrusted input. The original SMT implementation uses restricted Python `eval`, which still warrants careful validation and resource limits. Avoid executing untrusted formulas outside controlled tests; treat security/solver changes as separate, explicitly versioned work.
6. **Verify before claiming success:** run relevant tests and static checks, inspect the diff for unintended changes to original algorithm or benchmark, and report actual failures and limitations. Do not declare success on the basis of a mock-only test without saying so.
7. **Git discipline:** no `reset --hard`, force-push, history rewrite, mass formatting, unrelated dependency upgrades, or automatic merge. Do not commit generated run directories, API secrets, large logs, or ZIPs. Push/commit only when requested by the user or the agreed task.

### Useful commands

```bash
# No API calls; safe to run frequently
poetry run python scripts/run_rq1.py --dry-run --dev --samples 1
poetry run python scripts/run_rq1.py --dry-run --samples 8

# Offline RQ1 regression suite
poetry run pytest -q \
  tests/test_rq1.py tests/test_rq1_sampling.py \
  tests/test_rq1_storage.py tests/test_rq1_evaluation.py \
  tests/test_rq1_integration.py

# Project checks (report any pre-existing failures separately)
poetry run pytest -q
poetry run mypy
poetry run ruff check .

git status --short
git diff --check
# Compare protected datasets against the original reference:
git diff --exit-code 7ffd1ae -- benchmark/lifted_auto_eval benchmark/lifted
```

Run Ruff on changed files when repository-wide Ruff has unrelated pre-existing violations. Do not hide or mass-fix unrelated baseline warnings. Check formatting with `poetry run ruff format --check <changed-python-files>` where applicable; do not auto-format unrelated files. Match new code to the existing Python 3.11+ style and Poetry dependency setup.

## Known limitations to preserve and investigate

- **Signature parsing:** splitting `swap(things: Tuple[int, int])` on commas invents a second argument. Keep a minimal reproduction; do not silently change the benchmark to avoid it.
- **Heterogeneous tuple/sequence translation:** `Tuple[int, int, str]` is not faithfully represented by a homogeneous Z3 sequence in the original checker; `parse_input` is a relevant diagnostic case.
- **Solver unknown:** strings, sequences, quantifiers, and the fixed original timeout may yield `unknown`. Capture status, `reason_unknown()` where possible, formulas, and reproductions; do not label this a Z3 bug without evidence.
- **Swallowed provider errors:** the original extraction/client may mask API failures or try unsupported Groq completion endpoints. Preserve attempts and HTTP diagnostics; do not silently apply a previously developed provider workaround to a frozen study.
- **Incomplete traces:** some original repair paths lose initial/repair history. Preserve the RQ1 trace observer and distinguish unavailable initial metrics from zero success.
- **Weak agreement:** spec and code formulas can agree while both disagree with gold. Cross-channel equivalence is not a correctness oracle.

Bug fixes that affect the results must be evaluated as a **new, explicitly labeled scorer/pipeline version**; the original run remains an immutable reference. Distinguish confirmed implementation defects, model failures, inconclusive solver outcomes, and methodological limitations.

## Codex skills: Superpowers + mattpocock/skills

These are **workflow aids, not research methodology**. Their installation and availability depend on the Codex environment; this file does not install or guarantee any skill. Discover available skills and read their current `SKILL.md` instructions before invoking them. Never claim to have used an unavailable skill.

- For a substantial feature: use the installed Superpowers design/planning/review workflow (`brainstorming`, `writing-plans`, `test-driven-development`, `requesting-code-review`, `verification-before-completion`, etc.) **when applicable**. Keep the plan proportional to the task.
- For ambiguous requirements or shared vocabulary: use mattpocock's `grill-with-docs` **when the user invokes it**, or an available design/spec skill. For bugs, use `diagnosing-bugs`; for focused test-first work, use `tdd` if installed.
- If multiple installed skills cover the same step, choose **one** primary workflow instead of duplicating ceremonies (for example, do not run two TDD frameworks over the same change). Explicit user-invoked skills take precedence when compatible with research invariants.
- Agent/subagent coding workflows are allowed for engineering work, but **do not add multi-agent generation to thesis experiments** unless explicitly requested.
- Skills must not override the rules against gold leakage, implicit protocol changes, live API costs, or fabricated evidence.

## Completion report

For each coding task, end with: what changed, files touched, research impact (none or explicit), tests/checks actually run and results, known risks, and the commit hash **if** a commit was made. If a check could not run, say why. For experiment tasks, also identify the exact run/manifest and whether results are complete or exploratory.
