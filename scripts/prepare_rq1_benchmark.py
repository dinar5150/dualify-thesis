#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from dualify.rq1_benchmark import prepare_benchmark, verify_benchmark  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Prepare and verify the offline RQ1 benchmark")
    parser.add_argument("--source-root", type=Path, default=ROOT)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()

    try:
        action = verify_benchmark if args.verify_only else prepare_benchmark
        action(
            source_root=args.source_root.resolve(),
            output_dir=args.output_dir.resolve(),
            seed=args.seed,
        )
    except (KeyError, OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    print("SPLIT_FROZEN")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
