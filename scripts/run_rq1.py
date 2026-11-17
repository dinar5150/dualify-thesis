#!/usr/bin/env python3
"""Print a plan for the RQ1 extraction experiment; no live execution yet."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))

from dualify.rq1 import ExperimentConfig, make_plan  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument('--dev', action='store_true', help='Select six debugging cases')
    selection.add_argument('--case-id', action='append', help='Select a path-qualified case ID')
    parser.add_argument('--samples', type=int, default=8, help='Samples per case and channel')
    parser.add_argument('--model', help='Model to record in the plan')
    parser.add_argument('--temperature', type=float, help='Initial temperature to record')
    parser.add_argument('--dry-run', action='store_true', help='Print the plan without LLM calls')
    args = parser.parse_args()
    if not args.dry_run:
        parser.error('Live execution is not implemented; use --dry-run')
    try:
        config = ExperimentConfig(args.samples, args.model, args.temperature)
        plan = make_plan(ROOT, config, dev=args.dev, case_ids=args.case_id)
    except ValueError as exc:
        parser.error(str(exc))
    print(json.dumps({
        'selected_case_ids': list(plan.cases),
        'number_of_cases': len(plan.cases),
        'samples_per_channel': config.samples,
        'total_planned_extraction_attempts': plan.total_attempts,
        'model': config.model,
        'initial_temperature': config.temperature,
    }, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
