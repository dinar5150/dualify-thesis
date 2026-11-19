# RQ1 contract sampling

The full plan uses all 40 original `lifted_auto_eval` cases. The six-case dev selection is for debugging only; its results are not scientific findings. Original discovery uses bare function names that are not unique. The selection ID is the repository-relative source path with `/` replaced by `::`, followed by `::` and the original benchmark ID (with `.` replaced by `::`). The original IDs and files are unchanged.

```bash
poetry run python scripts/run_rq1.py --dev --samples 1 --dry-run
poetry run python scripts/run_rq1.py --samples 8 --dry-run
```

Protocol `rq1-upstream-adapter-v3` uses the unchanged original extraction, validation, repair, normalization and applicable fallback. An RQ1 client adapter supplies the initial temperature and retains the original repair default. Earlier protocols and their manifests are not resume-compatible. Defaults are eight samples per channel, initial temperature 0.7, and original repair temperature 0.0. No gold scoring, action planning or candidate selection is performed. Degraded or vacuous contracts are preserved without a correctness judgment.

## Upstream reuse audit

Discovery, extraction, validation, normalization, fallback and gold scoring call the
original Dualify modules. The manifest hashes all source and benchmark input files;
`compute_fingerprint` alone does not identify the full pipeline or environment.
Transcript replay/resume can return cached responses and is rejected for new RQ1
slots; recording clients alone do not capture all provider failures. The upstream
health summary infers an initial stage when trace data is missing, so it cannot
safely supply RQ1 initial-validity or repair denominators. Returned traces are
retained as-is and missing stages remain unavailable. RQ1 pass@k and immutable slot
storage have no equivalent in the upstream aggregate and JSON writers.

## Dev smoke test and resume

Set `GROQ_API_KEY` or `DUALIFY_API_KEY` in the environment or the root `.env`. The following starts a **live** dev smoke test with at most two attempts; it requires a new output directory. Keep the same chat setting for every invocation. Default provider, model and base URL are Groq's OpenAI-compatible API, `qwen/qwen3.8-27b`, and `https://api.groq.com/openai`.

```bash
export DUALIFY_OPENAI_USE_CHAT=1
poetry run python scripts/run_rq1.py --run --dev --samples 1 \
  --output-dir results/rq1-dev-smoke --inter-request-seconds 10 --max-new-attempts 2
```

Resume the same experiment without regenerating completed slots:

```bash
export DUALIFY_OPENAI_USE_CHAT=1
poetry run python scripts/run_rq1.py --run --resume --dev --samples 1 \
  --output-dir results/rq1-dev-smoke --inter-request-seconds 10 --max-new-attempts 2
```

Remove `--max-new-attempts` to continue all remaining slots. The limit is per invocation and does not change the experiment selection or manifest. Use the same selection, model, provider, URL, sample count, temperature, pacing and chat environment setting on resume. A change of commit, source/input hash, Python or Z3 version is also rejected. Use a fresh directory for a different experiment. Results under `results/` are gitignored; copy the entire directory to persistent storage when moving between Kaggle sessions. Use `--case-id` repeatedly for explicit debug selections; it cannot be combined with `--dev`.

## Files and status

- `manifest.json`: unique experiment ID, UTC start, commit, source/input hash, benchmark and selected IDs, sample and temperature configuration, model/provider/URL, Python and Z3 versions, pacing and chat setting. Secrets are not stored.
- `attempts/<slot-hash>/started-<attempt-id>.json`: durable start marker. Several markers can exist if a slot was interrupted and resumed.
- `attempts/<slot-hash>/result.json`: one atomic terminal record per experiment/case/channel/sample. Its checksum covers the candidate data. It includes initial response, the original returned stage trace, final extraction, degraded/fallback provenance, status, errors, elapsed time and available diagnostics. Original successful repairs can lose earlier trace stages; those metrics remain unavailable.

A slot with no `result.json` is incomplete and is retried on resume. A `result.json` with status `error` is a **completed failed attempt** and is retained in the denominator; it is not retried. A completed result takes precedence over earlier start markers. Corrupt JSON, checksum/identity mismatches, unexpected files and incomplete temporary writes cause resume to stop rather than silently discard records. The `.lock` file prevents concurrent writers sharing a filesystem; do not run copies of the same directory on separate hosts or merge them blindly. Filesystem support for atomic hard links and fsync is required.

## Diagnostics and limits

For the original OpenAI-compatible client, scoped instrumentation counts high-level calls and HTTP requests, 429s, retries, provider HTTP failures, and time spent in 429 retry sleeps. It records usage objects only when the provider supplies them. Calls and retries inside a process interrupted before a terminal result are not recovered; the start marker remains. Other clients have null HTTP-level metrics. Client-internal parsing errors or failed modes that recover may be invisible unless exposed as HTTP failures; extraction-caught exceptions are recorded; a later successful repair or model-derived salvage can recover the attempt. The instrumentation does not change the original retry policy. It temporarily wraps the synchronous HTTP and sleep functions; use the runner single-threaded. Pacing applies between high-level calls and not between internal retry requests. `DUALIFY_OPENAI_USE_CHAT=1` is supported and recorded in the manifest.

## Offline gold evaluation and analysis

Run these only after generation, on trusted experiment files. Neither command contacts an LLM. Use new output directories outside the generation directory:

```bash
poetry run python scripts/evaluate_rq1.py --run-dir results/rq1-run \
  --output-dir results/rq1-evaluation
poetry run python scripts/analyze_rq1.py --evaluation results/rq1-evaluation/evaluation.json \
  --output-dir results/rq1-analysis
```

The evaluation directory contains `evaluation.json` and per-candidate `candidates.csv`. It uses the original `score_extraction_against_gold` and checks that the benchmark and gold files match the original commit. It records the gold hash, evaluation commit and Z3 version. Results require the original benchmark checkout; compare the recorded generation and evaluation Z3 versions. The analysis directory contains `analysis.json`, per-task `tasks.csv`, `summary.md`, and `pass_at_k.svg`. Existing output directories are not overwritten.

Only terminal result files enter the denominator. A final pass@k for a task is available only with exactly eight terminal outcomes, a usable gold contract and no offline evaluation exception; scientific macro values require all 40 original tasks. The metric is proven-success yield: API failures, original runner fallbacks, invalid candidates and solver unknowns are not proven successes. Unknowns do not prove incorrectness. Offline evaluator failures withhold the estimate for the task. Unknown is inconclusive, not a proof of inequivalence. A degraded model-generated candidate can be a success when it passes the extractor's validation and the original scorer proves equivalence. The initial result is reconstructed only when the response and saved initial trace agree; otherwise it is unavailable. Initial API failures without a response count as unsuccessful. Initial pass@k is withheld when a needed initial result cannot be reconstructed.

Validity counts include Python expression syntax, the original parse/type gate, and the original extractor's full validation, with known and unavailable denominators. The repair rate is successful original repairs divided by initially invalid candidates; the report also gives attempts, unsuccessful repairs and unavailable outcomes. Fallbacks do not count as successful repairs. Counts are not gold correctness.

Generation, extraction, and offline evaluation failures are separate outcomes. Fallback, invalid/unsupported, unscorable, parse error, unknown, proven equivalent and proven strength remain distinct. Directional labels are assigned only if preconditions are proven equivalent and the original common-domain postcondition relation establishes a direction. Other combinations are `unclassified`; both original relations are retained. Syntactic unique rate includes normalized preconditions and postcondition and is not semantic diversity.

Cost totals cover observed terminal attempts only, excluding interrupted work. Missing telemetry is shown as unavailable or partial. Marginal time uses k multiplied by the observed mean duration per attempt, not a measurement of a stopped-early run or a monetary charge; it is shown only with complete 40-task timing coverage. The frequently cited 4/40 baseline is unverified and is not used as a comparison. The older paper-run has 36 scorable tasks, 5 spec and 6 code equivalents under a different model; it is not a matched baseline. Dev/partial means are exploratory and never scientific macro values. The original formula evaluation and Z3 behavior are unchanged; do not evaluate untrusted generated expressions.

## Diagnostic reports

After offline evaluation, run:

```bash
poetry run python scripts/diagnose_rq1.py --run-dir results/rq1-run \
  --evaluation results/rq1-evaluation/evaluation.json --output-dir results/rq1-diagnostics
```

The JSON and Markdown reports attach each observation to its case, channel, sample, source record, input, formula, expected and actual behavior, errors, solver and provider diagnostics, versions and reproduction command. They distinguish confirmed signature-parser defects from model/specification mismatches, observations and suspected implementation risks. An unknown result is not evidence of a Z3 bug; timeout or incomplete-theory causes are only reported if present in the saved data. Evaluation and generation records are cross-checked; legacy evaluation files without source checksums are flagged as unverifiable for freshness.

See [KAGGLE_RQ1.md](KAGGLE_RQ1.md) for a complete CPU workflow, pinning, secret handling, resume, offline reports and ZIP export.

The [final infrastructure review](RQ1_FINAL_REVIEW.md) records unchanged baseline components, the confirmed tuple-signature issue and remaining methodological limitations.
