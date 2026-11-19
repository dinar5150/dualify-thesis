#!/usr/bin/env python3
"""Evaluate persisted RQ1 attempts offline against original Dualify gold."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import z3

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from dualify.rq1_evaluation import evaluate_experiment, verify_provenance  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    if (
        args.output_dir.resolve() == args.run_dir.resolve()
        or args.run_dir.resolve() in args.output_dir.resolve().parents
    ):
        parser.error("Evaluation output must be outside the generation directory")
    baseline = "7ffd1ae37822096d5b7b573785ee46e877903185"
    try:
        verify_provenance(ROOT, baseline)
        extractors = ["src/dualify/phases/p01_spec_to_logic.py",
                      "src/dualify/phases/p02_code_to_logic.py"]
        if subprocess.run(["git", "diff", "--quiet", baseline, "--", *extractors],
                          cwd=ROOT).returncode:
            raise ValueError("Extraction validation code differs from RQ1 reference")
        evaluation = evaluate_experiment(ROOT, args.run_dir)
        evaluation["evaluator_version"] = "rq1-evaluation-v3"
        evaluation["evaluation_source_sha256"] = {
            str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in [*sorted((ROOT / "src/dualify").rglob("*.py")), Path(__file__)]
        }
        evaluation["evaluation_git_sha"] = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip()
        evaluation["evaluation_z3_version"] = z3.get_version_string()
        generation_z3 = evaluation["configuration"].get("z3_version")
        evaluation["warnings"] = (
            ["Generation and evaluation Z3 versions differ or generation version is unavailable."]
            if generation_z3 != evaluation["evaluation_z3_version"]
            else []
        )
        args.output_dir.mkdir(parents=True, exist_ok=False)
        (args.output_dir / "evaluation.json").write_text(
            json.dumps(evaluation, ensure_ascii=False, indent=2) + "\n"
        )
        with (args.output_dir / "candidates.csv").open("w", newline="", encoding="utf-8") as stream:
            rows = evaluation["candidates"]
            fields = (
                list(rows[0]) if rows else ["case_id", "benchmark_id", "channel", "sample_index"]
            )
            writer = csv.DictWriter(stream, fieldnames=fields)
            writer.writeheader()
            for row in rows:
                writer.writerow(
                    {
                        k: json.dumps(v, ensure_ascii=False, sort_keys=True)
                        if isinstance(v, (dict, list))
                        else v
                        for k, v in row.items()
                    }
                )
    except (ValueError, OSError) as exc:
        parser.exit(1, f"Error: {exc}\n")
    print(f"Evaluated {len(evaluation['candidates'])} terminal attempts in {args.output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
