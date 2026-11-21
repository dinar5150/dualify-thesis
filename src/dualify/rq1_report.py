"""Offline-анализ сохранённых финальных кандидатов RQ1."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from dataclasses import replace
from math import comb
from pathlib import Path
from random import Random
from statistics import mean, quantiles
from typing import Any

import z3

from dualify.gold_scoring import (
    DEFAULT_GOLD_DIR,
    GoldContract,
    load_gold_benchmark,
    score_extraction_against_gold,
)
from dualify.phases.p03_smt_checking import CaseSpec, is_parseable
from dualify.rq1_attempt import AttemptRecord
from dualify.rq1_pool import PoolIntegrityError, read_candidate_pool

K_VALUES = (1, 2, 4)
POOL_SIZE = 4
CHANNELS = ("spec", "code")
STATUSES = ("equivalent", "non_equivalent", "invalid", "inconclusive")
BOOTSTRAP_SEED = 20261120
BOOTSTRAP_RESAMPLES = 10_000


class AnalysisBlockedError(RuntimeError):
    """Для расчёта недостаточно подтверждённых данных."""


def _candidate(record: AttemptRecord, gold: GoldContract) -> dict[str, Any]:
    case = CaseSpec(gold.benchmark_id, gold.arg_types, gold.return_type)
    try:
        score = score_extraction_against_gold(
            case_spec=case, gold=gold, extraction=record.extraction, include_diagnostics=True,
        )
        reason = score.reason.partition(":")[0]
        invalid = False
        if reason == "formula_parse_error":
            # Общий разбор может упасть из-за вывода типа одного символа из двух формул.
            reference = replace(
                record.extraction,
                domain_constraints=gold.domain_constraints,
                postcondition=gold.postcondition,
            )
            invalid = is_parseable(case, reference) and not is_parseable(case, record.extraction)
    except z3.Z3Exception as exc:
        raise AnalysisBlockedError(f"{record.slot_id}: unclassified: {exc}") from exc

    smt = score.smt
    # Отрицательный флаг scorer сам по себе не доказывает наличие контрпримера.
    status = "unclassified"
    if smt is not None:
        if score.contract_equivalent:
            if reason == "equivalent_no_mismatch":
                status = "equivalent"
        elif reason in ("solver_unknown", "vacuous_equivalence"):
            status = "inconclusive"
        elif invalid:
            status = "invalid"
        elif smt.counterexample is not None and reason in (
            "case_pre_spec", "case_pre_code", "case_post_spec", "case_post_code",
        ):
            status = "non_equivalent"
    if status == "unclassified":
        raise AnalysisBlockedError(
            f"{record.slot_id}: unclassified: {json.dumps(score.to_dict(), ensure_ascii=False)}"
        )

    assert smt is not None
    return {
        "slot_id": record.slot_id,
        "status": status,
        "reason": score.reason,
        "diagnostics": smt.diagnostics,
        "counterexample": smt.counterexample,
        "well_formedness": smt.well_formedness,
        "degraded": record.extraction.degraded,
        "degraded_reason": record.extraction.degraded_reason,
        "elapsed_seconds": record.elapsed_seconds,
        "logical_calls": record.logical_call_count,
        "repair_calls": sum(call.stage == "repair" for call in record.calls),
    }


def _pass_at_k(successes: int) -> dict[str, float]:
    # Считаем вероятность, что в подвыборке без возвращения есть хотя бы один успех.
    return {str(k): 1 - comb(POOL_SIZE - successes, k) / comb(POOL_SIZE, k) for k in K_VALUES}


def _task_channel(records: list[AttemptRecord], gold: GoldContract) -> dict[str, Any]:
    treatment = records[1:]  # Reader возвращает baseline, затем slots 1–4.
    candidates = [_candidate(record, gold) for record in records]
    statuses = [candidate["status"] for candidate in candidates[1:]]
    c = statuses.count("equivalent")
    u = statuses.count("inconclusive")
    unique = {
        (tuple(sorted(record.extraction.domain_constraints)), record.extraction.postcondition)
        for record in treatment
    }
    return {
        "c": c,
        "u": u,
        "low": _pass_at_k(c),
        "high": _pass_at_k(c + u),
        "first_k_observed": {str(k): int("equivalent" in statuses[:k]) for k in K_VALUES},
        "unique_final_formulas": len(unique),
        "baseline": candidates[0],
        "candidates": candidates[1:],
    }


def _totals(candidates: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        **{status: sum(row["status"] == status for row in candidates) for status in STATUSES},
        "completed_slots": len(candidates),
        "incomplete_slots": 0,
        "elapsed_seconds": sum(row["elapsed_seconds"] for row in candidates),
        "logical_calls": sum(row["logical_calls"] for row in candidates),
        "repair_calls": sum(row["repair_calls"] for row in candidates),
        "repaired_attempts": sum(row["repair_calls"] > 0 for row in candidates),
        "degraded": sum(row["degraded"] for row in candidates),
    }


def _bootstrap(tasks: list[dict[str, Any]]) -> dict[str, Any]:
    # Берём обе оценки и их разность из одной задачи при каждом переотборе.
    rows = [(t["low"]["1"], t["low"]["4"], t["low"]["4"] - t["low"]["1"]) for t in tasks]
    random = Random(BOOTSTRAP_SEED)
    means = [
        [mean(column) for column in zip(*random.choices(rows, k=len(rows)), strict=True)]
        for _ in range(BOOTSTRAP_RESAMPLES)
    ]
    intervals = {}
    labels = ("pass@1_low", "pass@4_low", "delta_4_1")
    for label, column in zip(labels, zip(*means, strict=True), strict=True):
        cutoffs = quantiles(column, n=40, method="inclusive")
        intervals[label] = [cutoffs[0], cutoffs[-1]]
    return {
        "seed": BOOTSTRAP_SEED,
        "resamples": BOOTSTRAP_RESAMPLES,
        "task_count": len(tasks),
        "intervals": intervals,
        "limitation": "Похожие задачи могут быть зависимы, поэтому интервалы могут быть узкими.",
    }


def _summarize(tasks: list[dict[str, Any]]) -> dict[str, Any]:
    metrics = {
        name: {str(k): mean(task[name][str(k)] for task in tasks) for k in K_VALUES}
        for name in ("low", "high", "first_k_observed")
    }
    return {
        "task_count": len(tasks),
        **metrics,
        "delta_4_1": mean(task["low"]["4"] - task["low"]["1"] for task in tasks),
        "delta_4_1_if_all_unknown_succeed": mean(
            task["high"]["4"] - task["high"]["1"] for task in tasks
        ),
        "bootstrap_95": _bootstrap(tasks),
        "mixed_task_fraction": mean(0 < task["c"] < POOL_SIZE for task in tasks),
        "duplicate_formula_fraction": mean(
            (POOL_SIZE - task["unique_final_formulas"]) / POOL_SIZE for task in tasks
        ),
        "baseline": _totals([task["baseline"] for task in tasks]),
        "treatment": _totals([candidate for task in tasks for candidate in task["candidates"]]),
    }


def analyze_candidate_pools(
    pool_dirs: Sequence[Path], *, gold_dir: Path = DEFAULT_GOLD_DIR,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Считывает artefacts одной конфигурации и оценивает их исходным gold scorer."""
    if not pool_dirs:
        raise AnalysisBlockedError("Не передано ни одного пула")

    pools: dict[str, list[AttemptRecord]] = {}
    sampling_config: dict[str, Any] | None = None
    for directory in pool_dirs:
        config, records = read_candidate_pool(directory)
        case_id = config["benchmark_id"]
        settings = {
            key: config.get(key) for key in (
                "model", "provider", "treatment_temperature", "max_transient_retries",
                "endpoint_sha256",
            )
        }
        if sampling_config is not None and sampling_config != settings:
            raise AnalysisBlockedError(f"{directory}: настройки пула отличаются от остальных")
        sampling_config = settings
        if case_id in pools:
            raise AnalysisBlockedError(f"Повторная задача: {case_id}")
        pools[case_id] = records

    try:
        gold_contracts = load_gold_benchmark(gold_dir, require_unique_ids=True)
    except (OSError, ValueError) as exc:
        raise AnalysisBlockedError(f"Ошибка загрузки gold: {exc}") from exc
    tasks: list[dict[str, Any]] = []
    for case_id, records in sorted(pools.items()):
        gold = gold_contracts.get(case_id)
        if gold is None:
            raise AnalysisBlockedError(f"{case_id}: нет gold с точным benchmark_id")
        tasks.append({
            "benchmark_id": case_id,
            **{
                channel: _task_channel([r for r in records if r.channel == channel], gold)
                for channel in CHANNELS
            },
        })

    return tasks, {
        "sampling": sampling_config,
        "method": {
            "pass_at_k": "low учитывает доказанные успехи, high добавляет inconclusive как успехи.",
            "oracle_scope": "Эквивалентность gold в поддерживаемом фрагменте Dualify.",
            "elapsed_seconds": "Сумма наблюдаемого времени полных attempts с ожиданиями.",
            "logical_calls": "Наблюдаемые вызовы generate_json, включая repair.",
            "campaign_wall_clock": "NA: в записях есть длительность отдельных attempts.",
            "http_calls_tokens_inference_latency": "NA: эти величины не измерены в records.",
        },
        **{channel: _summarize([task[channel] for task in tasks]) for channel in CHANNELS},
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pool_dirs", nargs="+", type=Path, metavar="POOL_DIR")
    parser.add_argument("--gold-dir", type=Path, default=DEFAULT_GOLD_DIR)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)

    try:
        tasks, summary = analyze_candidate_pools(args.pool_dirs, gold_dir=args.gold_dir)
    except (AnalysisBlockedError, PoolIntegrityError) as exc:
        print(f"BLOCKED: {exc}", file=sys.stderr)
        return 1

    args.output_dir.mkdir(parents=True, exist_ok=True)
    for name, data in (("tasks.json", tasks), ("summary.json", summary)):
        (args.output_dir / name).write_text(
            json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
