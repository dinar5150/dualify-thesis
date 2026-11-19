"""Aggregate offline RQ1 evaluation without additional solver or model calls."""

from __future__ import annotations

import json
import math
import statistics
from collections import Counter
from typing import Any

K_VALUES = (1, 2, 4, 8)
OUTCOMES = (
    "equivalent",
    "non_equivalent",
    "stronger",
    "weaker",
    "incomparable",
    "inconclusive",
    "invalid_or_unsupported",
    "fallback",
    "api_or_evaluation_failure",
    "generation_error",
    "extraction_error",
    "evaluation_error",
    "unclassified",
    "unscorable",
    "unavailable",
)
BASELINE = {
    "status": "unverified",
    "note": "The previously cited 4/40 lacks an identified source and is not a comparison.",
}


def pass_at_k(n: int, c: int, k: int) -> float:
    if n < 1 or c < 0 or c > n or k < 1 or k > n:
        raise ValueError("Require 0 <= c <= n and 1 <= k <= n")
    return 1.0 - (math.comb(n - c, k) / math.comb(n, k) if n - c >= k else 0.0)


def _outcomes(rows: list[dict[str, Any]], field: str) -> dict[str, int]:
    counts = Counter(row[field] for row in rows)
    if set(counts) - set(OUTCOMES):
        raise ValueError(f"Unexpected outcome(s): {sorted(set(counts) - set(OUTCOMES))}")
    return {name: counts.get(name, 0) for name in OUTCOMES}


def _validity(rows: list[dict[str, Any]], stage: str) -> dict[str, Any]:
    result: dict[str, Any] = {"completed_attempts": len(rows)}
    for field in ("syntactic", "parseable", "extractor_valid"):
        values = [(r.get(f"{stage}_validity") or {}).get(field) for r in rows]
        known = sum(value is not None for value in values)
        yes = sum(value is True for value in values)
        result[field] = {
            "valid": yes,
            "known": known,
            "unavailable": len(rows) - known,
            "rate_over_known": yes / known if known else None,
        }
    return result


def _cost(rows: list[dict[str, Any]]) -> dict[str, Any]:
    durations = [
        r["duration_seconds"] for r in rows if isinstance(r.get("duration_seconds"), (int, float))
    ]
    result: dict[str, Any] = {
        "completed_attempts": len(rows),
        "duration_observed": len(durations),
        "total_generation_seconds_observed": sum(durations) if durations else None,
        "mean_seconds": statistics.mean(durations) if durations else None,
        "median_seconds": statistics.median(durations) if durations else None,
    }
    for field in (
        "request_count",
        "http_request_count",
        "retry_count",
        "http_429_count",
        "rate_limit_wait_seconds",
    ):
        vals = [(r.get("diagnostics") or {}).get(field) for r in rows]
        known = [v for v in vals if isinstance(v, (int, float))]
        result[field] = {
            "observed_total": sum(known) if known else None,
            "attempts_observed": len(known),
            "attempts_total": len(rows),
            "complete": bool(rows) and len(known) == len(rows),
        }
    usages = [
        u
        for r in rows
        for u in ((r.get("diagnostics") or {}).get("token_usage") or [])
        if isinstance(u, dict)
    ]
    totals: dict[str, float] = {}
    for usage in usages:
        for name, value in usage.items():
            if isinstance(value, (int, float)):
                totals[name] = totals.get(name, 0) + value
    result["token_usage"] = {
        "observed_totals": totals or None,
        "usage_objects": len(usages),
        "complete": False,
        "note": "Coverage per request is unavailable; totals may be partial.",
    }
    return result


def analyze(evaluation: dict[str, Any]) -> dict[str, Any]:
    ids = evaluation["selected_case_ids"]
    n = evaluation["samples"]
    rows = evaluation["candidates"]
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {
        (case_id, channel): [] for case_id in ids for channel in ("spec", "code")
    }
    seen: set[tuple[str, str, int]] = set()
    for row in rows:
        key = (row["case_id"], row["channel"], row["sample_index"])
        if (
            (key[0], key[1]) not in grouped
            or not isinstance(key[2], int)
            or not 0 <= key[2] < n
            or key in seen
        ):
            raise ValueError(f"Unexpected or duplicate candidate: {key}")
        seen.add(key)
        grouped[(key[0], key[1])].append(row)
    task_results = []
    channels: dict[str, Any] = {}
    for channel in ("spec", "code"):
        channel_rows = [r for r in rows if r["channel"] == channel]
        tasks = []
        for case_id in ids:
            candidates = grouped[(case_id, channel)]
            completed = len(candidates)
            successes = sum(c["final_outcome"] == "equivalent" for c in candidates)
            initial_successes = sum(c["initial_outcome"] == "equivalent" for c in candidates)
            initial_known = all(
                c["initial_outcome"] not in ("unavailable", "unscorable", "evaluation_error",
                                             "api_or_evaluation_failure") for c in candidates
            )
            final_known = all(
                c.get("gold_available") is True and c["final_outcome"] not in
                ("unscorable", "evaluation_error", "unavailable", "api_or_evaluation_failure")
                for c in candidates
            )
            # Final n=8 metrics must never be computed from an incomplete or different plan.
            eligible = n == 8 and completed == 8 and final_known
            initial_eligible = eligible and initial_known
            initial_invalid = [
                c
                for c in candidates
                if c.get("initial_validity") is not None
                and not c["initial_validity"]["extractor_valid"]
            ]
            attempted = [c for c in initial_invalid if c.get("repair_attempted")]
            successful = [
                c
                for c in attempted
                if c.get("repair_outcome") in ("ordinary_repair", "safe_subset_repair")
            ]
            unknown = [c for c in initial_invalid
                       if c.get("repair_outcome", "unavailable") == "unavailable"]
            keys = {
                json.dumps(c["final_contract_key"], ensure_ascii=False, sort_keys=True)
                for c in candidates
                if c.get("final_contract_key") is not None
            }
            task = {
                "case_id": case_id,
                "channel": channel,
                "completed": completed,
                "planned": n,
                "incomplete": n - completed,
                "successes": successes,
                "pass_at_k": {
                    str(k): pass_at_k(8, successes, k) if eligible else None for k in K_VALUES
                },
                "initial_pass_at_k": {
                    str(k): pass_at_k(8, initial_successes, k) if initial_eligible else None
                    for k in K_VALUES
                },
                "validity": {stage: _validity(candidates, stage) for stage in ("initial", "final")},
                "repair": {
                    "initially_invalid": len(initial_invalid),
                    "repair_attempts": len(attempted),
                    "successful_repairs": len(successful),
                    "unsuccessful_repairs": sum(
                        c.get("repair_outcome") not in
                        ("ordinary_repair", "safe_subset_repair", "unavailable", None)
                        for c in attempted),
                    "repair_outcome_unavailable": len(unknown),
                    "outcomes": dict(Counter(c.get("repair_outcome", "unavailable")
                                             for c in candidates)),
                    "success_per_initially_invalid": len(successful) / len(initial_invalid)
                    if initial_invalid and not unknown
                    else None,
                },
                "outcomes": _outcomes(candidates, "final_outcome"),
                "initial_outcomes": _outcomes(candidates, "initial_outcome"),
                "degraded": sum(c.get("degraded") is True for c in candidates),
                "vacuous": sum(c.get("vacuous") is True for c in candidates),
                "unique_final_contracts": len(keys),
                "unique_rate": len(keys) / completed if completed else None,
                "cost": _cost(candidates),
            }
            tasks.append(task)
            task_results.append(task)
        by_stage: dict[str, Any] = {}
        for stage, field in (("final", "pass_at_k"), ("initial", "initial_pass_at_k")):
            table = {}
            for k in K_VALUES:
                vals = [t[field][str(k)] for t in tasks if t[field][str(k)] is not None]
                # Scientific headline requires complete original 40-task coverage.
                full = len(ids) == 40 and len(vals) == 40
                table[str(k)] = {
                    "macro": statistics.mean(vals) if full else None,
                    "eligible_tasks": len(vals),
                    "required_tasks": 40,
                    "exploratory_mean": statistics.mean(vals) if vals else None,
                }
            by_stage[stage] = table
        invalid = [
            r
            for r in channel_rows
            if r.get("initial_validity") is not None
            and not r["initial_validity"]["extractor_valid"]
        ]
        repairs = [r for r in invalid if r.get("repair_attempted")]
        repair_success = [
            r
            for r in repairs
            if r.get("repair_outcome") in ("ordinary_repair", "safe_subset_repair")
        ]
        repair_unknown = [r for r in invalid
                          if r.get("repair_outcome", "unavailable") == "unavailable"]
        channels[channel] = {
            "pass_at_k": by_stage,
            "validity": {s: _validity(channel_rows, s) for s in ("initial", "final")},
            "outcomes": _outcomes(channel_rows, "final_outcome"),
            "initial_outcomes": _outcomes(channel_rows, "initial_outcome"),
            "repair": {
                "initially_invalid": len(invalid),
                "repair_attempts": len(repairs),
                "successful_repairs": len(repair_success),
                "unsuccessful_repairs": sum(
                    r.get("repair_outcome") not in
                    ("ordinary_repair", "safe_subset_repair", "unavailable", None)
                    for r in repairs),
                "repair_outcome_unavailable": len(repair_unknown),
                "outcomes": dict(Counter(r.get("repair_outcome", "unavailable")
                                         for r in channel_rows)),
                "success_per_initially_invalid": len(repair_success) / len(invalid)
                if invalid and not repair_unknown
                else None,
            },
            "cost": _cost(channel_rows),
            "degraded": sum(r.get("degraded") is True for r in channel_rows),
            "vacuous": sum(r.get("vacuous") is True for r in channel_rows),
            "macro_unique_rate": statistics.mean(
                t["unique_rate"] for t in tasks if t["unique_rate"] is not None
            )
            if any(t["unique_rate"] is not None for t in tasks)
            else None,
        }
        # Estimated cumulative generation time uses observed mean per attempt;
        # it is not a measurement of monetary cost or a stopped-early experiment.
        costs = []
        previous_p = previous_t = 0.0
        for k in K_VALUES:
            p = by_stage["final"][str(k)]["macro"]
            durations = [
                t["cost"]["mean_seconds"]
                for t in tasks
                if t["completed"] == 8 and t["cost"]["duration_observed"] == 8
            ]
            elapsed = k * statistics.mean(durations) if len(ids) == len(durations) == 40 else None
            gain = p - previous_p if p is not None else None
            delta = elapsed - previous_t if elapsed is not None else None
            costs.append(
                {
                    "k": k,
                    "estimated_seconds_per_task": elapsed,
                    "incremental_seconds": delta,
                    "incremental_pass_gain": gain,
                    "seconds_per_pass_gain": delta / gain
                    if delta is not None and gain and gain > 0
                    else None,
                }
            )
            if p is not None:
                previous_p = p
            if elapsed is not None:
                previous_t = elapsed
        channels[channel]["marginal_cost"] = costs
    return {
        "experiment_id": evaluation["experiment_id"],
        "configuration": evaluation["configuration"],
        "baseline": BASELINE,
        "evaluation_warnings": evaluation.get("warnings", []),
        "selected_tasks": len(ids),
        "samples": n,
        "scientific_full_benchmark": all(
            channels[channel]["pass_at_k"]["final"]["1"]["macro"] is not None
            for channel in ("spec", "code")
        ),
        "channels": channels,
        "tasks": task_results,
    }
