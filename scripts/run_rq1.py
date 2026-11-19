#!/usr/bin/env python3
"""Plan or run independent RQ1 contract extractions."""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))

import z3  # noqa: E402

from dualify.ollama_client import create_llm_client  # noqa: E402
from dualify.rq1 import ExperimentConfig, make_plan  # noqa: E402
from dualify.rq1_storage import execute  # noqa: E402


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
    mode.add_argument('--run', action='store_true', help='Run sampling and persist results')
    parser.add_argument('--output-dir', type=Path,
                        help='Experiment directory (required with --run)')
    parser.add_argument('--resume', action='store_true', help='Resume an existing experiment')
    parser.add_argument('--max-new-attempts', type=int, help='Maximum new slots this invocation')
    parser.add_argument('--inter-request-seconds', type=float, default=0.0,
                        help='Minimum time between high-level LLM requests')
    args = parser.parse_args()
    if not args.dry_run and not args.run:
        parser.error('Specify --dry-run or --run')
    if args.run and args.output_dir is None:
        parser.error('--output-dir is required with --run')
    if args.dry_run and (args.resume or args.output_dir or args.max_new_attempts is not None):
        parser.error('--resume, --output-dir, and --max-new-attempts require --run')
    base = urlsplit(args.base_url)
    if base.username is not None or base.password is not None or base.query or base.fragment:
        parser.error('--base-url must not contain credentials, a query, or a fragment')
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
            digest = hashlib.sha256()
            paths = sorted((ROOT / 'src' / 'dualify').rglob('*.py'))
            paths += sorted((ROOT / 'benchmark' / 'lifted_auto_eval').glob('*.py'))
            paths += [Path(__file__)]
            for path in paths:
                digest.update(str(path.relative_to(ROOT)).encode())
                digest.update(path.read_bytes())
            configuration = {
                'protocol_version': 'rq1-dev-v2',
                'git_sha': subprocess.check_output(
                    ['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
                'source_and_inputs_sha256': digest.hexdigest(),
                'benchmark': 'lifted_auto_eval', 'selected_case_ids': list(plan.cases),
                'samples_per_channel': config.samples, 'initial_temperature': config.temperature,
                'repair_temperature': 0.0, 'model': config.model, 'provider': args.provider,
                'base_url': args.base_url.rstrip('/'), 'z3_version': z3.get_version_string(),
                'python_version': sys.version, 'inter_request_seconds': args.inter_request_seconds,
                'openai_use_chat': os.environ.get('DUALIFY_OPENAI_USE_CHAT'),
                'lock_sha256': hashlib.sha256((ROOT / 'poetry.lock').read_bytes()).hexdigest(),
                'dependency_versions': {name: importlib.metadata.version(name) for name in
                                        ('requests', 'PyYAML', 'z3-solver', 'python-dotenv')},
            }
            client = create_llm_client(provider=args.provider, model=config.model or '',
                                       base_url=args.base_url, api_key=key)
            result = execute(plan, client, args.output_dir, configuration, resume=args.resume,
                             max_new_attempts=args.max_new_attempts,
                             interval=args.inter_request_seconds)
        except (ValueError, RuntimeError, OSError) as exc:
            parser.exit(1, f'Error: {exc}\n')
        print(json.dumps(result, indent=2))
        return int(result.get('errors', 0) > 0)
    print(json.dumps(report, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
