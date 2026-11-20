#!/usr/bin/env python3
"""Create the fixed offline RQ1 dev/test manifest."""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import sys
from pathlib import Path

import yaml  # type: ignore[import-untyped]

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from dualify.io_utils import write_json  # noqa: E402

UPSTREAM_COMMIT = "7ffd1ae37822096d5b7b573785ee46e877903185"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _display_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def _build_manifest(input_dir: Path, gold_dir: Path, seed: int) -> dict[str, object]:
    input_paths = {path.stem: path for path in input_dir.glob("*.py")}
    gold_paths = {path.stem: path for path in gold_dir.glob("*.yaml")}
    if set(input_paths) != set(gold_paths):
        raise ValueError("input/gold filenames differ")
    if len(input_paths) != 40:
        raise ValueError(f"expected 40 input/gold pairs, found {len(input_paths)}")

    records: list[tuple[str, Path, Path]] = []
    for stem in sorted(input_paths):
        gold_path = gold_paths[stem]
        gold = yaml.safe_load(gold_path.read_text(encoding="utf-8"))
        records.append((str(gold["benchmark_id"]), input_paths[stem], gold_path))

    benchmark_ids = [benchmark_id for benchmark_id, _, _ in records]
    if len(set(benchmark_ids)) != 40:
        raise ValueError("duplicate benchmark_id in gold files")

    shuffled_ids = sorted(benchmark_ids)
    random.Random(seed).shuffle(shuffled_ids)
    dev_ids = set(shuffled_ids[:10])

    cases = []
    for benchmark_id, input_path, gold_path in sorted(records):
        cases.append(
            {
                "benchmark_id": benchmark_id,
                "split": "dev" if benchmark_id in dev_ids else "test",
                "input_path": _display_path(input_path),
                "gold_path": _display_path(gold_path),
                "input_sha256": _sha256(input_path),
                "gold_sha256": _sha256(gold_path),
            }
        )

    return {
        "source_commit": UPSTREAM_COMMIT,
        "seed": seed,
        "cases": cases,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input-dir", type=Path, default=ROOT / "benchmark" / "lifted_auto_eval"
    )
    parser.add_argument("--gold-dir", type=Path, default=ROOT / "benchmark" / "lifted")
    parser.add_argument(
        "--output", type=Path, default=ROOT / "docs" / "rq1" / "benchmark-manifest.json"
    )
    parser.add_argument("--seed", type=int, default=20261120)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    try:
        expected = _build_manifest(args.input_dir, args.gold_dir, args.seed)
        if args.check:
            actual = json.loads(args.output.read_text(encoding="utf-8"))
            if actual != expected:
                raise ValueError("manifest does not match current benchmark files")
            print(f"Verified {args.output}")
        else:
            write_json(args.output, expected)
            actual = json.loads(args.output.read_text(encoding="utf-8"))
            if actual != expected:
                raise ValueError("written manifest does not match generated data")
            print(f"Wrote and verified {args.output}")
    except (KeyError, OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
