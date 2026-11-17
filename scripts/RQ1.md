# RQ1 experiment plan

This stage plans the existing `lifted_auto_eval` benchmark. The full plan always includes all 40 original cases. The six-case dev selection is for debugging only; its results must not be presented as scientific findings. No LLM calls or live sampling are implemented in this stage.

Original benchmark discovery uses bare function names, which are not unique: several names occur in multiple files. The CLI therefore identifies a case as its repository-relative source path with `/` replaced by `::`, followed by `::` and the original benchmark ID (with any `.` replaced by `::`). The underlying original case IDs and files remain unchanged.

```bash
poetry run python scripts/run_rq1.py --dev --samples 1 --dry-run
poetry run python scripts/run_rq1.py --dev --samples 2 --dry-run
poetry run python scripts/run_rq1.py --samples 8 --dry-run --model qwen/qwen3.8-27b --temperature 0.7
poetry run python scripts/run_rq1.py --case-id 'benchmark::lifted_auto_eval::crosshair_examples_PEP316_correct_code_arith.py_double.py::double' --dry-run
```

Use `--case-id` multiple times to select named original cases. It cannot be combined with `--dev`. A dry run prints IDs and the planned attempt count; specifying an ID selects a debugging plan, not the full experiment.
