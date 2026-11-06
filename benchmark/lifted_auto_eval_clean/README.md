# Annotation-free inputs for the 40-case benchmark

The original 40 Python snippets are in `benchmark/lifted_auto_eval/`. Seven of
those snippets contain PEP 316 `pre:` or `post:` directives in their function
docstrings. The code-to-logic extractor includes the whole function source in
its prompt, so those directives expose the reference contract during
generation. One example (`_assert_double_swap_does_nothing`) also exposes the
`post:` directive to spec-to-logic because discovery takes the docstring when
there is no preceding natural-language comment.

This directory contains **40 frozen input copies**. Preparation removes only
standalone formal contract directive lines inside function docstrings. It keeps
ordinary descriptions, examples, type annotations, and executable statements.
Only seven source files differ from their originals. The other 33 copies are
byte-for-byte identical. The original sources and the 40 gold YAML files in
`benchmark/lifted/` are unchanged.

For example, the original PEP 316 `double` source contains:

```python
post: len(_) == len(items) * 2
```

The cleaned copy omits that directive. The corresponding reference in
`benchmark/lifted/` still has `Length(ret) == Length(items) * 2`, which is loaded
only by gold scoring after generation.

## Use

Run the frozen clean benchmark (requires an LLM endpoint):

```sh
poetry run dualify-run --benchmark lifted_auto_eval_clean --provider openai \
  --base-url https://api.groq.com/openai --model qwen/qwen3.8-27b
```

The six-task `dev_small` subset uses the same cleaned inputs; keep the remaining
34 tasks out of iterative prompt/method tuning. Record the exact git revision,
model, parameters, prompt version and input directory with every result.
Outputs from `lifted_auto_eval` and `lifted_auto_eval_clean` have different
inputs and must not be pooled as one baseline. Previously recorded transcripts
may not replay against the cleaned input prompts.

## Reproduce and verify

From the repository root:

```sh
python scripts/prepare_clean_benchmark.py
poetry run pytest -q tests/test_clean_benchmark.py tests/test_dev_small.py
```

`manifest.json` lists all 40 stems and the **Git blob SHA-1** of the original
Python source, cleaned Python input and unchanged gold YAML. These IDs pin
file contents, not semantic validity. `prepare_clean_benchmark.py` deterministically
regenerates the cleaned files from their originals. The tests check the full
40-to-40 file mapping, source and gold hashes, exact sanitizer output, p01 and
p02 prompt inputs, and the correspondence with `dev_small`.

The sanitizer removes explicitly labelled PEP 316 directives only. It does not
strip ordinary English requirements, examples or code comments. Some English
descriptions are quite close to the gold. This is acceptable for the
spec-to-logic channel, whose task is to formalize requirements, but it is an
experimental limitation when interpreting code-to-logic results. The inputs
still contain docstrings and code comments. They are **not code-only** inputs.
An empty or missing annotation does not prove the absence of every form of
answer leakage. Benchmark suitability and the adequacy of the gold contracts
must be evaluated separately.
