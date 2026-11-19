#!/usr/bin/env python3
"""Summarize an offline RQ1 evaluation into JSON, CSV, Markdown and SVG."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from dualify.rq1_analysis import K_VALUES, analyze  # noqa: E402


def _display(value: Any) -> str:
    return (
        "unavailable"
        if value is None
        else f"{value:.4f}"
        if isinstance(value, float)
        else str(value)
    )


def _markdown(report: dict[str, Any]) -> str:
    lines = [
        "# RQ1 offline analysis",
        "",
        f"Experiment: `{report['experiment_id']}`; selected tasks: {report['selected_tasks']}; "
        f"planned samples per channel: {report['samples']}.",
        "",
        "Scientific macro values require all 40 original tasks with eight terminal outcomes "
        "per channel. Dev and partial means are exploratory only.",
        "",
        "| Channel | k | Final macro | Exploratory final mean | Eligible tasks | Initial macro |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for channel, content in report["channels"].items():
        for k in K_VALUES:
            final = content["pass_at_k"]["final"][str(k)]
            initial = content["pass_at_k"]["initial"][str(k)]
            lines.append(
                f"| {channel} | {k} | {_display(final['macro'])} | "
                f"{_display(final['exploratory_mean'])} | "
                f"{final['eligible_tasks']} / {report['selected_tasks']} | "
                f"{_display(initial['macro'])} |"
            )
    if report["evaluation_warnings"]:
        lines.extend(["", "Evaluation warnings: " + "; ".join(report["evaluation_warnings"])])
    for channel, content in report["channels"].items():
        lines.extend(
            [
                "",
                f"## {channel}",
                "",
                f"Final outcomes: `{json.dumps(content['outcomes'], sort_keys=True)}`.",
                "",
                f"Initial outcomes: `{json.dumps(content['initial_outcomes'], sort_keys=True)}`.",
                "",
                f"Validity: `{json.dumps(content['validity'], sort_keys=True)}`.",
                "",
                f"Repair: `{json.dumps(content['repair'], sort_keys=True)}`.",
                "",
                f"Degraded: {content['degraded']}; vacuous: {content['vacuous']}; "
                "exploratory macro syntactic unique rate: "
                f"{_display(content['macro_unique_rate'])} "
                "(distinct final contracts / terminal slots, including failures and fallbacks).",
                "",
                f"Cost: `{json.dumps(content['cost'], sort_keys=True)}`.",
                "",
                "Estimated marginal costs: "
                f"`{json.dumps(content['marginal_cost'], sort_keys=True)}`.",
            ]
        )
    lines.extend(
        [
            "",
            "## Baseline",
            "",
            "Original baseline: temperature 0.0; spec 4/40; code 4/40; approximately 4h 42m. "
            "RQ1 uses the manifest temperature. Differences from baseline pass@1 cannot "
            "be attributed solely to sample count.",
            "",
            "Unknown solver results are not proven successes. Stronger/weaker/incomparable "
            "labels require equivalent preconditions and a proven postcondition relation; "
            "other combinations remain unclassified. Syntactic uniqueness is not semantic "
            "equivalence. Cost estimates are time, not monetary charges.",
            "",
        ]
    )
    return "\n".join(lines)


def _svg(report: dict[str, Any]) -> str:
    lines = [
        '<svg xmlns="http://www.w3.org/2000/svg" width="680" height="390" viewBox="0 0 680 390">',
        '<rect width="680" height="390" fill="white"/>',
        '<text x="45" y="28" font-family="sans-serif" font-size="18">'
        "Macro pass@k (complete 40-task runs only)</text>",
        '<path d="M 65 55 V 320 H 630" stroke="black" fill="none"/>',
    ]
    for y in range(0, 11, 2):
        py = 320 - y * 26
        lines.append(f'<text x="25" y="{py + 4}" font-size="11">{y / 10:.1f}</text>')
        lines.append(f'<path d="M 65 {py} H 630" stroke="#dddddd"/>')
    xs = [115, 255, 395, 535]
    for x, k in zip(xs, K_VALUES, strict=True):
        lines.append(f'<text x="{x}" y="342" font-size="13">{k}</text>')
    lines.append('<text x="340" y="370" font-size="14">k</text>')
    any_line = False
    for channel, color, label_y in [("spec", "#1866a3", 62), ("code", "#d34b22", 80)]:
        vals = [
            report["channels"][channel]["pass_at_k"]["final"][str(k)]["macro"] for k in K_VALUES
        ]
        lines.append(f'<text x="540" y="{label_y}" fill="{color}" font-size="12">{channel}</text>')
        if all(v is not None for v in vals):
            points = " ".join(f"{x},{320 - 260 * v:.2f}" for x, v in zip(xs, vals, strict=True))
            lines.append(
                f'<polyline points="{points}" fill="none" stroke="{color}" stroke-width="3"/>'
            )
            any_line = True
    if not any_line:
        lines.append(
            '<text x="110" y="190" font-size="15">'
            "Complete macro results are not yet available.</text>"
        )
    lines.append("</svg>")
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evaluation", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    try:
        evaluation = json.loads(args.evaluation.read_text())
        report = analyze(evaluation)
        args.output_dir.mkdir(parents=True, exist_ok=False)
        (args.output_dir / "analysis.json").write_text(json.dumps(report, indent=2) + "\n")
        (args.output_dir / "summary.md").write_text(_markdown(report))
        (args.output_dir / "pass_at_k.svg").write_text(_svg(report))
        with (args.output_dir / "tasks.csv").open("w", newline="", encoding="utf-8") as stream:
            rows = report["tasks"]
            writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
            writer.writeheader()
            for row in rows:
                writer.writerow(
                    {
                        k: json.dumps(v, sort_keys=True) if isinstance(v, (dict, list)) else v
                        for k, v in row.items()
                    }
                )
    except (ValueError, OSError, KeyError) as exc:
        parser.exit(1, f"Error: {exc}\n")
    print(f"Wrote analysis to {args.output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
