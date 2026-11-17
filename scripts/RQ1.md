# RQ1 contract sampling

The full plan uses all 40 original `lifted_auto_eval` cases. The six-case dev selection is for debugging only; its results are not scientific findings. Original benchmark discovery uses bare function names that are not unique. Case selection therefore uses a repository-relative source path with `/` replaced by `::`, followed by `::` and the original benchmark ID (with any `.` replaced by `::`). Original benchmark IDs and files are unchanged.

```bash
poetry run python scripts/run_rq1.py --dev --samples 1 --dry-run
poetry run python scripts/run_rq1.py --samples 8 --dry-run
poetry run python scripts/run_rq1.py --case-id 'benchmark::lifted_auto_eval::crosshair_examples_PEP316_correct_code_arith.py_double.py::double' --dry-run
```

The default is eight candidates for each case and channel, with initial temperature 0.7 and the original repair temperature 0.0. Set `--samples`, `--model`, and `--temperature` to change the plan. The same settings apply to every candidate within a run. Use `--case-id` multiple times to select original cases; it cannot be combined with `--dev`.

For a live run, configure `GROQ_API_KEY` or `DUALIFY_API_KEY` in the environment or root `.env`, then explicitly use `--run` instead of `--dry-run`. Defaults are provider `openai`, base URL `https://api.groq.com/openai`, and model `qwen/qwen3.8-27b`; the provider and URL can be changed with `--provider` and `--base-url`. No live requests are made by dry runs or tests.

The loop independently invokes the original extractor for each candidate, including its validation, repair, normalization and applicable original fallback. No action planning, gold scoring, voting or candidate selection occurs. Each candidate records its qualified and original IDs, channel and sample index, the initial client response, validation and repair traces, pre-fallback and final `ExtractionResult`, fallback provenance, and observable errors. If a client call fails and the original extractor catches it, the candidate retains its output but has status `error`. An original client's internally handled errors may not be visible to the wrapper. Degraded and vacuous results are retained without assigning correctness.

This stage keeps results in memory until the loop finishes and prints them to stdout; it has no persistence, resume, rate pacing, or crash recovery. Provider retry diagnostics may also appear on stdout. An interrupted run can lose all results. Token usage and transport retries are not collected. The extraction trace observer preserves original intermediate validation steps even when the extractor replaces its payload after repair; the original returned `ExtractionResult` itself is unchanged.
