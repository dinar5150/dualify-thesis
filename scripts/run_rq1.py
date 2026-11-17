#!/usr/bin/env python3
"""Plan or run independent RQ1 contract extractions."""
from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))

from dualify.ollama_client import create_llm_client  # noqa: E402
from dualify.rq1 import ExperimentConfig, make_plan, sample_plan  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument('--dev', action='store_true', help='Select six debugging cases')
    selection.add_argument('--case-id', action='append', help='Select a path-qualified case ID')
    parser.add_argument('--samples', type=int, default=8, help='Samples per case and channel')
    parser.add_argument('--model', default='qwen/qwen3.8-27b')
    parser.add_argument('--temperature', type=float, default=0.7, help='Initial temperature')
    parser.add_argument('--provider', choices=['openai', 'ollama'], default='openai')
    parser.add_argument('--base-url', default='https://api.groq.com/openai')
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--dry-run', action='store_true', help='Print plan without LLM calls')
    mode.add_argument('--run', action='store_true', help='Run sampling and print results')
    args = parser.parse_args()
    if not args.dry_run and not args.run:
        parser.error('Specify --dry-run or --run')
    try:
        config = ExperimentConfig(args.samples, args.model, args.temperature)
        plan = make_plan(ROOT, config, dev=args.dev, case_ids=args.case_id)
    except ValueError as exc:
        parser.error(str(exc))
    report = {
        'selected_case_ids': list(plan.cases),
        'number_of_cases': len(plan.cases),
        'samples_per_channel': config.samples,
        'total_planned_extraction_attempts': plan.total_attempts,
        'model': config.model,
        'initial_temperature': config.temperature,
    }
    if args.run:
        key = os.environ.get('DUALIFY_API_KEY') or os.environ.get('GROQ_API_KEY', '')
        try:
            client = create_llm_client(provider=args.provider, model=config.model or '',
                                       base_url=args.base_url, api_key=key)
            client.healthcheck()
        except (ValueError, RuntimeError) as exc:
            parser.exit(1, f'Error: {exc}\n')
        candidates = list(sample_plan(plan, client))
        report['candidates'] = [asdict(candidate) for candidate in candidates]
        print(json.dumps(report, indent=2))
        return int(any(candidate.status == 'error' for candidate in candidates))
    print(json.dumps(report, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
