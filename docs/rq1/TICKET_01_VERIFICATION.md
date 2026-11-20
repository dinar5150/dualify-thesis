# Ticket 01 verification record

**Status:** `SPLIT_FROZEN`
**Date:** 2026-11-20
**Ticket base:** `eca293043c4c2b1d9615e556a7829e3c739044e4`
**Original upstream:** `7ffd1ae37822096d5b7b573785ee46e877903185`

## Environment

- Python 3.14.4
- Poetry 2.5.1
- pytest 8.4.2
- ruff 0.13.3
- mypy 1.19.1

## Frozen dataset result

- 40 unique IDs paired by identical input/gold stem.
- 10 dev / 30 held-out test across 27 groups; no group crosses the split.
- Dev balance: 4 CrossHair / 6 Python-by-Contract and 2 `needs_attention`.
- Audit coverage: 40/40 cases.
- Audit findings: 8 cases with embedded formal annotations/directives, 15 with
  too-general descriptions, and 1 exact gold-formula overlap in source input.
- Source metadata discrepancy: gold README declares 8 `needs_attention`; the
  actual YAML records contain 7. YAML values are used and the discrepancy is
  retained in the audit.

## Checksums

The corpus aggregate is SHA-256 over the sorted per-file `sha256sum` output.

| Artifact | SHA-256 |
| --- | --- |
| 40 input `.py` aggregate | `6872106138d9c63ea32f4b1253c9c68183d4be81d1180a01007de33adf97d2c6` |
| 40 gold `.yaml` aggregate | `e111a2059d5d19c5124152b21793e8d32fb96666344787eb11de26a0de1e1445` |
| `benchmark/rq1_groups.yaml` | `b32299749180f7ec9b89f1bb80601aa211c6036a9c6d0df91d15ad1028b40c03` |
| `benchmark/rq1_audit_rules.yaml` | `46bb15c65b8656f4717dbe594a9102d41c133eda6ff2f6cf48b7bcf85ec23a89` |
| `benchmark/rq1/manifest.json` | `b25d66cfd2d3db6deef7aa4ade989a7920eae941aca91d95112fea0a5200e01e` |
| `benchmark/rq1/audit.json` | `6dc92e5a8f130387ffc768a0464b5578331f6ccb84d4d67d4c796c28a81fdbc5` |

## Reproduction and verification commands

```bash
poetry run python scripts/prepare_rq1_benchmark.py \
  --source-root . --output-dir benchmark/rq1 --seed 20261120
poetry run python scripts/prepare_rq1_benchmark.py \
  --source-root . --output-dir benchmark/rq1 --seed 20261120 --verify-only
poetry run pytest -q tests/test_rq1_benchmark.py
poetry run ruff check .
poetry run mypy src tests
poetry run pytest -q
git diff --name-only eca293043c4c2b1d9615e556a7829e3c739044e4 \
  -- benchmark/lifted_auto_eval benchmark/lifted
```

## Pre-review results

| Command | Result |
| --- | --- |
| `poetry run pytest -q tests/test_rq1_benchmark.py` | 12 passed |
| `poetry run pytest -q tests/test_dataset_pipeline.py tests/test_gold_scoring.py` | 9 passed |
| `poetry run ruff check src/dualify/rq1_benchmark.py scripts/prepare_rq1_benchmark.py tests/test_rq1_benchmark.py` | passed |
| `poetry run mypy src/dualify/rq1_benchmark.py tests/test_rq1_benchmark.py` | passed |
| `poetry run pytest -q` | 113 passed, 1 skipped |
| `poetry run ruff check .` | failed on 172 pre-existing findings outside Ticket 01, mainly generated benchmark/result inputs and older scripts |
| `poetry run mypy src tests` | failed on the pre-existing unused `type: ignore` in `src/dualify/gold_scoring.py:9` |

The two full-project quality failures are present outside this ticket's diff and
were not changed because Ticket 01 forbids unrelated fixes and edits to benchmark
inputs. The changed Python files pass both tools.

Two fresh temporary output directories were generated with the same command and
seed. `cmp` succeeded for both `manifest.json` and `audit.json`, and both also
matched the committed artifacts byte-for-byte. `git diff --exit-code` against
the ticket base for `benchmark/lifted_auto_eval` and `benchmark/lifted` succeeded
with no output, confirming the original 40 inputs and 40 gold files are unchanged.

## Independent review

The two review axes used the fixed diff
`git diff eca293043c4c2b1d9615e556a7829e3c739044e4...4cb1ebb`.

- **Standards:** no hard documented-standard violations. One non-blocking LOW
  judgement call suggested replacing nested `dict[str, Any]` records with
  TypedDict/dataclasses. Not changed: the current module is a single narrow
  offline slice, tests cover its public CLI, and adding a type hierarchy is not
  required by Ticket 01.
- **Spec:** HIGH finding that generation could accept drift present before its
  first run; MEDIUM finding that literal phrase matching missed broad specs such
  as `determine_row` and `determine_column`. Both confirmed and fixed with
  regression tests, an immutable corpus lock, and a manual case-level registry.

## Post-review focused re-verification

| Command/check | Result |
| --- | --- |
| `poetry run pytest -q tests/test_rq1_benchmark.py` | 13 passed, including drift-before-generation regression |
| related dataset/gold tests | 9 passed |
| ruff on changed Python files | passed |
| mypy on changed module/tests | passed |
| `poetry run pytest -q` | 114 passed, 1 skipped |
| two fresh generations plus `cmp` against each other and committed artifacts | byte-identical |
| source/gold `git diff --exit-code` from ticket base | passed, no changes |

The final hashes in the checksum table are from this post-review generation.
