# RQ1 contract sampling

The full plan uses all 40 original `lifted_auto_eval` cases. The six-case dev selection is for debugging only; its results are not scientific findings. Original discovery uses bare function names that are not unique. The selection ID is the repository-relative source path with `/` replaced by `::`, followed by `::` and the original benchmark ID (with `.` replaced by `::`). The original IDs and files are unchanged.

```bash
poetry run python scripts/run_rq1.py --dev --samples 1 --dry-run
poetry run python scripts/run_rq1.py --samples 8 --dry-run
```

Sampling uses the original extraction, validation, repair, normalization and applicable fallback. Defaults are eight samples per channel, initial temperature 0.7, and original repair temperature 0.0. No gold scoring, action planning or candidate selection is performed. Degraded or vacuous contracts are preserved without a correctness judgment.

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
- `attempts/<slot-hash>/result.json`: one atomic terminal record per experiment/case/channel/sample. Its checksum covers the candidate data. It includes initial response, original stage trace, final extraction, degraded/fallback provenance, status, errors, elapsed time and available diagnostics.

A slot with no `result.json` is incomplete and is retried on resume. A `result.json` with status `error` is a **completed failed attempt** and is retained in the denominator; it is not retried. A completed result takes precedence over earlier start markers. Corrupt JSON, checksum/identity mismatches, unexpected files and incomplete temporary writes cause resume to stop rather than silently discard records. The `.lock` file prevents concurrent writers sharing a filesystem; do not run copies of the same directory on separate hosts or merge them blindly. Filesystem support for atomic hard links and fsync is required.

## Diagnostics and limits

For the original OpenAI-compatible client, scoped instrumentation counts high-level calls and HTTP requests, 429s, retries, provider HTTP failures, and time spent in 429 retry sleeps. It records usage objects only when the provider supplies them. Calls and retries inside a process interrupted before a terminal result are not recovered; the start marker remains. Other clients have null HTTP-level metrics. Client-internal parsing errors or failed modes that recover may be invisible unless exposed as HTTP failures; extraction-caught exceptions are recorded and mark the result as an error. The instrumentation does not change the original retry policy. It temporarily wraps the synchronous HTTP and sleep functions; use the runner single-threaded. Pacing applies between high-level calls and not between internal retry requests. `DUALIFY_OPENAI_USE_CHAT=1` is supported and recorded in the manifest.
