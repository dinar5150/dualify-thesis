# RQ1 benchmark freeze (Ticket 01)

This directory contains the generated, offline-only dataset boundary for RQ1.
The original files in `benchmark/lifted_auto_eval/` and `benchmark/lifted/` remain
unchanged.

## Reproduce and verify

From the repository root:

```bash
poetry run python scripts/prepare_rq1_benchmark.py \
  --source-root . \
  --output-dir benchmark/rq1 \
  --seed 20261120

poetry run python scripts/prepare_rq1_benchmark.py \
  --source-root . \
  --output-dir benchmark/rq1 \
  --seed 20261120 \
  --verify-only
```

Both commands finish with `SPLIT_FROZEN`. They make no model/API calls. The
generation command writes `manifest.json` and `audit.json`, then immediately
verifies them against the current source files. `--verify-only` does not rewrite
the artifacts.

## Files and rules

- `manifest.json` pairs each input `.py` with the gold `.yaml` having the same
  filesystem-safe stem. It records all 40 unique benchmark IDs, full SHA-256
  hashes, provenance, group membership, and the exact 10 dev / 30 test split.
- `audit.json` records source provenance, embedded formal annotations with line
  evidence, exact gold-text overlap, informal-spec quality, and gold limitations
  for every case, plus summary counters.
- `../rq1_groups.yaml` is the reviewed grouping input. It covers exact clones,
  variants with different names, near-clones, and direct helper/caller families.
  Unlisted cases become explicit singleton groups.
- `../rq1_audit_rules.yaml` anchors the original input/gold trees to immutable
  upstream SHA-256 digests and records manually reviewed broad-spec decisions.
  The lock is checked before generation writes any artifact.

The split algorithm searches whole-group subsets of exactly 10 cases. Among
valid subsets it minimizes deviation from the rounded corpus proportions for
source origin and `needs_attention`; seed `20261120` breaks remaining ties via
SHA-256. The frozen dev split reaches both targets: 4 CrossHair cases and 2
`needs_attention` cases.

## Audit interpretation

The audit reports eight cases containing formal annotations/directives, fifteen
cases with descriptions classified as too general, and one exact reference
formula already present in a generation input (`even_fibb`, `n >= 0`). These are
disclosed threats to validity; no case was edited or removed.

The gold README says eight records are flagged `needs_attention`, while the 40
actual YAML files contain seven such flags. The audit records both values and
marks the discrepancy. The YAML records are authoritative for the split and
case-level quality metadata.
