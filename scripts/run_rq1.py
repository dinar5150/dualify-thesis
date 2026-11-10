"""Run RQ1 sampling without changing the existing dualify-run CLI.

From repo root: poetry run python scripts/run_rq1.py --num-samples 8
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from dualify.rq1_sampling import SamplingConfig, run_rq1


def main() -> None:
    parser = argparse.ArgumentParser(
        description="RQ1: repeated full-pipeline samples and pass@k"
    )
    parser.add_argument(
        "--benchmark", choices=["dev_small", "lifted_auto_eval_clean"], default="dev_small"
    )
    parser.add_argument(
        "--allow-holdout", action="store_true", help="Required for the 40-task final benchmark"
    )
    parser.add_argument("--num-samples", type=int, default=8)
    parser.add_argument("--temperature", type=float, default=0.7)
    parser.add_argument(
        "--ks", nargs="+", type=int, default=None,
        help="Default: 1 2 4 8, capped at num-samples",
    )
    parser.add_argument("--model", default="qwen/qwen3.8-27b")
    parser.add_argument("--base-url", default="https://api.groq.com/openai")
    parser.add_argument("--provider", choices=["openai", "ollama"], default="openai")
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument(
        "--replay", type=Path, default=None,
        help="Replay a completed JSONL transcript offline",
    )
    parser.add_argument(
        "--resume-transcript", type=Path, default=None,
        help="Replay cached prefix, then continue live",
    )
    args = parser.parse_args()
    if args.ks is None:
        ks = tuple(k for k in (1, 2, 4, 8) if k <= args.num_samples)
    else:
        ks = tuple(args.ks)
    config = SamplingConfig(
        benchmark=args.benchmark,
        allow_holdout=args.allow_holdout,
        num_samples=args.num_samples,
        temperature=args.temperature,
        ks=ks,
        model=args.model,
        base_url=args.base_url,
        provider=args.provider,
    )
    output = run_rq1(
        config, output_dir=args.output_dir,
        replay=args.replay, resume=args.resume_transcript,
    )
    metrics = json.loads((output / "metrics.json").read_text(encoding="utf-8"))
    print("\n[RQ1] Macro pass@k (final pipeline results):")
    for channel in ("spec_final", "code_final"):
        print(f"  {channel}: {metrics['macro'][channel]['pass_at_k']}")
    print(f"[RQ1] Reports: {output}")


if __name__ == "__main__":
    main()
