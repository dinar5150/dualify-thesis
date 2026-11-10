"""Diagnose Z3's XOR and directional checks for RQ1 double candidates.

Run from the repository root, using the existing experiment output:

    poetry run python scripts/diagnose_gold_z3.py \
        results/rq1_dev_small_.../samples.json --repeat 3 --timeout-ms 5000

No LLM requests or file writes. Uses the formula parser that actually exists
in Dualify, and shares one Z3 scope for the gold and generated contracts.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

import z3

from dualify.gold_scoring import load_gold_benchmark
from dualify.phases.p03_smt_checking import (
    _augment_scope_from_formulas,
    _canonicalize_expression,
    _make_var,
    _safe_eval,
    _strip_exhaustive_zero_split_constraints,
)


def parse_pair(
    benchmark_id: str,
    arg_types: dict[str, str],
    return_type: str,
    gold_pre: list[str],
    gold_post: str,
    generated_pre: list[str],
    generated_post: str,
) -> tuple[z3.BoolRef, z3.BoolRef, z3.BoolRef, z3.BoolRef]:
    """Parse both contracts in the SAME scope, as check_equivalence does."""
    scope: dict[str, Any] = {
        name: _make_var(name, type_name)
        for name, type_name in arg_types.items()
    }
    scope["ret"] = _make_var("ret", return_type)
    known_names = set(scope)

    gold_constraints = _strip_exhaustive_zero_split_constraints(
        [_canonicalize_expression(s, benchmark_id) for s in gold_pre]
    )
    generated_constraints = _strip_exhaustive_zero_split_constraints(
        [_canonicalize_expression(s, benchmark_id) for s in generated_pre]
    )
    gold_post = _canonicalize_expression(gold_post, benchmark_id)
    generated_post = _canonicalize_expression(generated_post, benchmark_id)
    _augment_scope_from_formulas(
        scope,
        known_names,
        [*gold_constraints, *generated_constraints, gold_post, generated_post],
    )

    def convert(constraints: list[str], post: str) -> tuple[z3.BoolRef, z3.BoolRef]:
        pre_z3 = [_safe_eval(expr, scope, benchmark_id) for expr in constraints]
        post_z3 = _safe_eval(post, scope, benchmark_id)
        return (z3.And(*pre_z3) if pre_z3 else z3.BoolVal(True)), post_z3

    g_pre, g_post = convert(gold_constraints, gold_post)
    c_pre, c_post = convert(generated_constraints, generated_post)
    return g_pre, g_post, c_pre, c_post


def check(label: str, formula: z3.BoolRef, timeout_ms: int, repetitions: int) -> None:
    for i in range(1, repetitions + 1):
        solver = z3.Solver()
        solver.set("timeout", timeout_ms)
        solver.set("random_seed", 0)
        solver.add(formula)
        started = time.perf_counter()
        status = solver.check()
        elapsed_ms = (time.perf_counter() - started) * 1000
        reason = solver.reason_unknown() if status == z3.unknown else ""
        print(
            f"    {label:<20} repeat={i} status={str(status):<7} "
            f"elapsed={elapsed_ms:8.1f}ms reason={reason!r}",
            flush=True,
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("samples_json", type=Path)
    parser.add_argument("--timeout-ms", type=int, default=5000)
    parser.add_argument("--repeat", type=int, default=3)
    args = parser.parse_args()
    if args.timeout_ms < 1 or args.repeat < 1:
        parser.error("--timeout-ms and --repeat must be positive")

    with args.samples_json.open(encoding="utf-8") as file:
        data = json.load(file)
    tasks = data["tasks"]
    gold = load_gold_benchmark()
    print("Z3 version:", z3.get_version_string())
    print("Timeout per check:", args.timeout_ms, "ms")

    for task in tasks:
        task_id = task["task_id"]
        if not task_id.endswith("::double"):
            continue
        reference = gold.get(task_id)
        if reference is None:
            raise ValueError(f"Gold contract not found for {task_id}")

        # Take the exact candidate from the experiment, not a rewritten formula.
        candidate: dict[str, Any] | None = None
        for sample in task["samples"]:
            for channel in ("spec", "code"):
                final = sample[channel]["final"]
                if final.get("postcondition") == "ret == Concat(items, items)":
                    candidate = final
                    break
            if candidate is not None:
                break
        if candidate is None:
            print("Skipping", task_id, ": no Concat candidate")
            continue

        try:
            g_pre, g_post, c_pre, c_post = parse_pair(
                task_id,
                reference.arg_types,
                reference.return_type,
                reference.domain_constraints,
                reference.postcondition,
                candidate["domain_constraints"],
                candidate["postcondition"],
            )
        except Exception as exc:
            raise RuntimeError(f"Failed to parse gold/candidate for {task_id}: {exc}") from exc

        common_pre = z3.And(g_pre, c_pre)
        queries = {
            "XOR": z3.And(common_pre, z3.Xor(g_post, c_post)),
            "generated NOT gold": z3.And(common_pre, c_post, z3.Not(g_post)),
            "gold NOT generated": z3.And(common_pre, g_post, z3.Not(c_post)),
        }
        print(f"\n{task_id}\n  generated: {candidate['postcondition']}")
        print(f"  gold: {reference.postcondition}")
        for label, query in queries.items():
            check(label, query, args.timeout_ms, args.repeat)


if __name__ == "__main__":
    main()
