#!/usr/bin/env python3
"""Inspect saved RQ1 attempts and offline evaluation without model calls."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from dualify.rq1_diagnostics import diagnose  # noqa: E402


def markdown(report: dict[str, Any]) -> str:
    lines = [
        f"# RQ1 diagnostics: {report['experiment_id']}",
        "",
        f"Evaluated candidates: {report['evaluated_candidates']}.",
        "",
        "Counts are findings, not necessarily distinct candidates or confirmed bugs.",
        "",
        "| Category | Findings |",
        "|---|---:|",
    ]
    for category, count in report["counts"].items():
        lines.append(f"| {category} | {count} |")
    lines.extend(["", "## Limitations", ""])
    lines.extend(f"- {item}" for item in report["limitations"])
    lines.extend(["", "## Findings"])
    for n, item in enumerate(report["findings"], 1):
        lines.extend(
            [
                "",
                f"### {n}. {item['category']} ({item['classification']})",
                "",
                f"- Case: `{item['case_id']}`; original ID: `{item['benchmark_id']}`.",
                f"- Channel: {item['channel']}; sample: {item['sample_index']}.",
                f"- Signature: `{item['signature']}`.",
                f"- Expected: `{json.dumps(item['expected'], ensure_ascii=False)}`.",
                f"- Actual: `{json.dumps(item['actual'], ensure_ascii=False)}`.",
                f"- Generation SHA: `{item['git_sha']}`; Z3: `{item['generation_z3_version']}`.",
                f"- Evaluation SHA: `{item['evaluation_git_sha']}`; "
                f"Z3: `{item['evaluation_z3_version']}`.",
                f"- Source record: `{item['source_record']}`.",
                f"- Reproduce: `{item['reproduction']}`.",
                "",
                "Input:",
                "```text",
                str(item["input"]),
                "```",
                "",
                "Formulas, errors, evidence, and provider diagnostics:",
                "```json",
                json.dumps(
                    {
                        k: item[k]
                        for k in (
                            "initial_formula",
                            "initial_preconditions",
                            "formula",
                            "preconditions",
                            "errors",
                            "api_diagnostics",
                            "gold_result",
                            "evidence",
                        )
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                "```",
            ]
        )
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--evaluation", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    out = args.output_dir.resolve()
    run = args.run_dir.resolve()
    if out == run or run in out.parents:
        parser.error("Diagnostics output must be outside the generation directory")
    try:
        evaluation = json.loads(args.evaluation.read_text(encoding="utf-8"))
        report = diagnose(ROOT, args.run_dir, evaluation, args.evaluation)
        args.output_dir.mkdir(parents=True, exist_ok=False)
        (args.output_dir / "diagnostics.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        (args.output_dir / "diagnostics.md").write_text(markdown(report), encoding="utf-8")
    except (ValueError, OSError, KeyError, TypeError) as exc:
        parser.exit(1, f"Error: {exc}\n")
    print(f"Wrote {len(report['findings'])} findings to {args.output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
