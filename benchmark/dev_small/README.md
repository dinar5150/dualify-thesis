# Development subset

`manifest.json` freezes six unique gold benchmark IDs and their source file stems.
The selection is `random.Random(42).sample(sorted(source files), 6)`, sorted by
stem for the manifest, from the 40 `lifted_auto_eval/*.py` files. The remaining
34 are holdout tasks; do not tune on them. Discovery sorts by short function
name, and the runner uses the source file stem to resolve each original YAML in
`benchmark/lifted/`. In particular, the two `double` cases have the same
runner `benchmark_id` but different file stems and gold IDs. Use the manifest
ID or `gold_scoring.gold_benchmark_id`, not the short name, when joining results.

These are copies of the original snippets, with one intentional change: the
PEP316 `double` docstring's formal `post:` directive is removed because it
expresses the reference contract and the code extractor receives the source.
The natural-language requirement and implementation are retained. Gold YAMLs
are read from the original directory only for evaluation, after generation;
they are not copied into this directory or supplied to prompts. Consequently,
results for this one case are not strictly input-identical to a full benchmark
run. The original benchmark and all 40 reference YAMLs remain unchanged.

Set `GROQ_API_KEY` in your shell without putting the key in a command, file, or
transcript. An existing nonempty `DUALIFY_API_KEY` takes precedence, so unset it
if you intend to use `GROQ_API_KEY`. Run from the repository root:

```sh
poetry run dualify-run --benchmark dev_small --provider openai \
  --base-url https://api.groq.com/openai --model qwen/qwen3.8-27b
```

To record a baseline, choose a new transcript filename for each run:

```sh
poetry run dualify-run --benchmark dev_small --provider openai \
  --base-url https://api.groq.com/openai --model qwen/qwen3.8-27b \
  --record-transcript results/dev_small_baseline.jsonl
```

Recording truncates an existing transcript at that path. Replay makes no API
requests and validates each prompt hash in recorded order:

```sh
poetry run dualify-run --benchmark dev_small --provider openai \
  --base-url https://api.groq.com/openai --model qwen/qwen3.8-27b \
  --replay results/dev_small_baseline.jsonl
```

Keep the source, prompts and code version fixed for replay. Divergent prompts or
calls cause an error; replay is not a fresh independent sample. Transcripts
contain prompts and responses. Reports are written to `results/dev_small_<UTC
timestamp>.json`, separate by filename from `results/lifted_auto_eval_*.json`.
Files generated within the same second with the same benchmark name can
collide; archive or rename reports between rapid runs. Results are gitignored.

In the report, `summary.gold_scoring` and each case's `gold_scoring.spec` and
`.code` give p01/p02 comparison to gold; inspect their reason distributions for
parse errors and `solver_unknown`. `summary.cross_check` and each case's
`smt_checking` describe p01 versus p02, including solver-unknown and
low-confidence cases. `extractor_health` and extraction traces expose degraded,
weak, repaired and fallback outcomes. A provider failure can abort a run before
it writes a report; it is not necessarily counted as a failed case. A false
`equivalent` value alone does not distinguish inconclusive from inequivalent;
inspect the reason. Gold scoring applies to the final extraction, including any
fallback or degradation, so interpret it together with health fields.

Limitations: `HistogramOfDeltas` currently maps to a Z3 sequence. `Contains(histo,
Unit(1))` tests sequence membership, **not** whether key `1` is present in a
Python dictionary. A parseable or satisfiable candidate is not necessarily a
semantically correct contract. Keep this distinction when interpreting scores.

The existing runner does not implement pass@k or independent sampling controls;
future experiments need separate samples, unique task IDs, and a selection
policy that does not consult gold. This subset does not change those mechanisms.
