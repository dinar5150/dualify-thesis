"""Offline evaluation of persisted RQ1 candidates using the original gold scorer."""

from __future__ import annotations

import ast
import fcntl
import hashlib
from dataclasses import asdict
from pathlib import Path
from typing import Any

from dualify import gold_scoring
from dualify.formula_parser import normalize_formula
from dualify.phases import p01_spec_to_logic, p02_code_to_logic
from dualify.phases.p03_smt_checking import CaseSpec, is_parseable
from dualify.rq1 import discover_cases
from dualify.rq1_storage import _digest, _read, slot_key
from dualify.runner import _normalize_extraction
from dualify.types import BenchmarkCase, ExtractionResult


def _syntactic(extraction: ExtractionResult) -> bool:
    try:
        for expr in [*extraction.domain_constraints, extraction.postcondition]:
            ast.parse(expr, mode="eval")
        return True
    except (ValueError, TypeError, SyntaxError):
        return False


def _spec(case: BenchmarkCase) -> CaseSpec:
    return CaseSpec(
        benchmark_id=case.benchmark_id, arg_types=case.arg_types, return_type=case.return_type
    )


def validity(case: BenchmarkCase, channel: str, extraction: ExtractionResult) -> dict[str, Any]:
    """Apply the original extractor's validation and parser/type gate."""
    phase = p01_spec_to_logic if channel == "spec" else p02_code_to_logic
    allowed = phase._extract_signature_args(case.signature)
    source = case.informal_spec if channel == "spec" else case.function_source
    extra = phase._extract_self_symbols(source + "\n" + case.extra_context)
    payload = phase._coerce_payload(asdict(extraction), allowed, case.return_type)
    errors = phase._validate_payload(payload, allowed, extra)
    if not errors:
        errors = phase._typecheck_errors(
            payload["domain_constraints"],
            payload["postcondition"],
            case.arg_types,
            case.return_type,
        )
    return {
        "syntactic": _syntactic(extraction),
        "parseable": is_parseable(_spec(case), extraction),
        "extractor_valid": not errors,
        "validation_errors": errors,
    }


def _initial(
    case: BenchmarkCase, channel: str, data: dict[str, Any]
) -> tuple[ExtractionResult | None, dict[str, Any] | None]:
    response, trace = data.get("initial_response"), data.get("stage_trace")
    if not isinstance(response, dict) or not isinstance(trace, dict):
        return None, None
    initial = trace.get("initial")
    if not isinstance(initial, dict) or not isinstance(initial.get("errors"), list):
        return None, None
    phase = p01_spec_to_logic if channel == "spec" else p02_code_to_logic
    allowed = phase._extract_signature_args(case.signature)
    payload = phase._normalize_payload_formulas(
        phase._coerce_payload(response, allowed, case.return_type)
    )
    if payload["postcondition"] != initial.get("postcondition") or payload[
        "domain_constraints"
    ] != initial.get("domain_constraints"):
        return None, None
    extraction = ExtractionResult(
        benchmark_id=case.benchmark_id,
        args=payload["args"],
        return_type=payload["return_type"],
        domain_constraints=payload["domain_constraints"],
        postcondition=payload["postcondition"],
        confidence=payload["confidence"],
        notes=payload["notes"],
    )
    result = {
        "syntactic": _syntactic(extraction),
        "parseable": is_parseable(_spec(case), extraction),
        "extractor_valid": not initial["errors"],
        "validation_errors": initial["errors"],
    }
    # Use the same bool normalization the original runner applies after extraction.
    normalized = ExtractionResult(
        **_normalize_extraction(_spec(case), extraction.postcondition, asdict(extraction))
    )
    return normalized, result


def _contract_key(extraction: ExtractionResult) -> list[Any]:
    # Syntactic identity only; sorting preconditions matches gold exact-match handling.
    return [
        sorted(normalize_formula(x) for x in extraction.domain_constraints if x.strip()),
        normalize_formula(extraction.postcondition),
    ]


def _score(
    case: BenchmarkCase, gold: gold_scoring.GoldContract | None, extraction: ExtractionResult | None
) -> dict[str, Any] | None:
    if gold is None or extraction is None:
        return None
    case_spec = CaseSpec(
        benchmark_id=case.benchmark_id, arg_types=gold.arg_types, return_type=gold.return_type
    )
    return asdict(
        gold_scoring.score_extraction_against_gold(
            case_spec=case_spec, gold=gold, extraction=extraction
        )
    )


def classify(
    score: dict[str, Any] | None,
    valid: bool | None,
    *,
    failed: bool = False,
    fallback: bool = False,
) -> str:
    """Mutually exclusive outcomes, using only original solver and relation results."""
    if failed:
        return "api_or_evaluation_failure"
    if fallback:
        return "fallback"
    if valid is not True:
        return "invalid_or_unsupported"
    if score is None or score.get("skipped"):
        return "unscorable"
    reason = str(score.get("reason", "")).split(":", 1)[0]
    pre, post = score.get("pre_relation"), score.get("post_relation")
    if reason == "formula_parse_error" or "parse_error" in (pre, post):
        return "invalid_or_unsupported"
    if reason == "solver_unknown" or "undetermined" in (pre, post):
        return "inconclusive"
    if score.get("contract_equivalent"):
        return "equivalent"
    # Post relation is conditional on the common precondition. Only classify
    # direction when the original scorer proved the preconditions equivalent.
    if pre == "equivalent" and isinstance(post, str):
        return {
            "generated_stronger": "stronger",
            "generated_weaker": "weaker",
            "incomparable": "incomparable",
        }.get(post, "unclassified")
    return "unclassified"


def evaluate_record(
    case: BenchmarkCase, data: dict[str, Any], gold: gold_scoring.GoldContract | None
) -> dict[str, Any]:
    channel = data["channel"]
    entry: dict[str, Any] = {
        "case_id": data["case_id"],
        "benchmark_id": data["benchmark_id"],
        "channel": channel,
        "sample_index": data["sample_index"],
        "generation_status": data["status"],
        "generation_errors": data.get("errors", []),
        "gold_available": gold is not None and gold.in_fragment,
        "used_fallback": bool(data.get("used_fallback")),
        "initial_validity": None,
        "final_validity": None,
        "initial_gold": None,
        "final_gold": None,
        "initial_outcome": "unavailable",
        "final_outcome": "unavailable",
        "initial_error": None,
        "final_error": None,
        "final_contract_key": None,
        "degraded": None,
        "degraded_reason": None,
        "pre_fallback_degraded": (data.get("extraction_before_fallback") or {}).get("degraded"),
        "vacuous": None,
        "repair_attempted": False,
        "diagnostics": data.get("diagnostics"),
        "duration_seconds": data.get("duration_seconds"),
    }
    trace = data.get("stage_trace")
    entry["repair_attempted"] = isinstance(trace, dict) and "repair" in trace
    try:
        initial, entry["initial_validity"] = _initial(case, channel, data)
        if initial is not None:
            entry["initial_gold"] = _score(case, gold, initial)
            entry["initial_outcome"] = classify(
                entry["initial_gold"], entry["initial_validity"]["extractor_valid"]
            )
        elif data.get("initial_response") is None and data.get("status") == "error":
            entry["initial_outcome"] = "api_or_evaluation_failure"
    except Exception as exc:
        entry["initial_outcome"] = "api_or_evaluation_failure"
        entry["initial_error"] = f"{type(exc).__name__}: {exc}"
    final: ExtractionResult | None = None
    try:
        if isinstance(data.get("final_extraction"), dict):
            final = ExtractionResult(**data["final_extraction"])
            entry["final_validity"] = validity(case, channel, final)
            entry["final_gold"] = _score(case, gold, final)
            entry["final_contract_key"] = _contract_key(final)
            entry["degraded"] = final.degraded
            entry["degraded_reason"] = final.degraded_reason
            entry["vacuous"] = normalize_formula(final.postcondition).replace(" ", "") == "ret==ret"
        entry["final_outcome"] = classify(
            entry["final_gold"],
            entry["final_validity"]["extractor_valid"]
            if entry["final_validity"] is not None
            else None,
            failed=data.get("status") == "error",
            fallback=entry["used_fallback"],
        )
    except Exception as exc:
        entry["final_outcome"] = "api_or_evaluation_failure"
        entry["final_error"] = f"{type(exc).__name__}: {exc}"
    return entry


def evaluate_experiment(root: Path, run_dir: Path) -> dict[str, Any]:
    if not (run_dir / "manifest.json").is_file():
        raise ValueError("Missing experiment manifest")
    with (run_dir / ".lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_SH | fcntl.LOCK_NB)
        return _evaluate_experiment(root, run_dir)


def _evaluate_experiment(root: Path, run_dir: Path) -> dict[str, Any]:
    manifest = _read(run_dir / "manifest.json")
    if manifest.get("schema_version") != 1 or not isinstance(manifest.get("experiment_id"), str):
        raise ValueError("Invalid experiment manifest")
    config, plan = manifest.get("configuration"), manifest.get("plan")
    if not isinstance(config, dict) or not isinstance(plan, dict):
        raise ValueError("Invalid experiment configuration or plan")
    cases = discover_cases(root)
    ids, n = plan.get("case_ids"), plan.get("samples")
    if (
        not isinstance(ids, list)
        or not ids
        or len(ids) != len(set(ids))
        or not isinstance(n, int)
        or isinstance(n, bool)
        or n < 1
        or any(i not in cases for i in ids)
    ):
        raise ValueError("Invalid case IDs or sample count in manifest")
    if (
        config.get("benchmark") != "lifted_auto_eval"
        or config.get("selected_case_ids") != ids
        or config.get("samples_per_channel") != n
    ):
        raise ValueError("Manifest configuration and plan disagree")
    expected_slots = {
        slot_key(identifier, channel, index): {
            "case_id": identifier,
            "benchmark_id": cases[identifier].benchmark_id,
            "channel": channel,
            "sample_index": index,
        }
        for identifier in ids
        for channel in ("spec", "code")
        for index in range(n)
    }
    attempts = run_dir / "attempts"
    if attempts.exists():
        for slot in attempts.iterdir():
            if not slot.is_dir() or slot.name not in expected_slots:
                raise ValueError(f"Unexpected attempt slot: {slot}")
            for path in slot.iterdir():
                if path.name == "result.json":
                    continue
                if not (path.name.startswith("started-") and path.suffix == ".json"):
                    raise ValueError(f"Unexpected incomplete file: {path}")
                marker = _read(path)
                if (
                    marker.get("status") != "running"
                    or marker.get("experiment_id") != manifest["experiment_id"]
                    or path.name != f"started-{marker.get('attempt_id')}.json"
                    or not marker.get("started_at")
                    or any(marker.get(k) != v for k, v in expected_slots[slot.name].items())
                ):
                    raise ValueError(f"Invalid attempt start record: {path}")
    gold_records = gold_scoring.load_gold_benchmark(root / "benchmark" / "lifted")
    lookup = gold_scoring.build_gold_lookup(gold_records)
    entries = []
    for identifier in ids:
        case = cases[identifier]
        gold = gold_scoring.lookup_gold_contract(
            case.benchmark_id, gold_records, lookup, source_file=case.file
        )
        # Never accept the scorer's ambiguous bare-name fallback for this benchmark.
        if gold is not None and gold.safe_id != Path(case.file).stem:
            gold = None
        for channel in ("spec", "code"):
            for index in range(n):
                slot = run_dir / "attempts" / slot_key(identifier, channel, index)
                path = slot / "result.json"
                if not path.exists():
                    continue
                saved = _read(path)
                data = saved.get("data")
                expected = {
                    "case_id": identifier,
                    "benchmark_id": case.benchmark_id,
                    "channel": channel,
                    "sample_index": index,
                }
                if (
                    not isinstance(data, dict)
                    or saved.get("experiment_id") != manifest["experiment_id"]
                    or saved.get("checksum") != _digest(data)
                    or saved.get("status") not in ("completed", "error")
                    or data.get("status") != saved.get("status")
                    or any(data.get(k) != v or saved.get(k) != v for k, v in expected.items())
                ):
                    raise ValueError(f"Invalid attempt record: {path}")
                attempt_id = saved.get("attempt_id")
                if (
                    not isinstance(attempt_id, str)
                    or not attempt_id.isalnum()
                    or not (slot / f"started-{attempt_id}.json").is_file()
                ):
                    raise ValueError(f"Missing attempt start record: {path}")
                evaluation = evaluate_record(case, data, gold)
                evaluation["source_record_checksum"] = saved["checksum"]
                entries.append(evaluation)
    gold_hash = hashlib.sha256()
    for path in sorted((root / "benchmark" / "lifted").glob("*.yaml")):
        gold_hash.update(path.name.encode())
        gold_hash.update(path.read_bytes())
    return {
        "schema_version": 1,
        "experiment_id": manifest["experiment_id"],
        "configuration": config,
        "selected_case_ids": ids,
        "samples": n,
        "gold_sha256": gold_hash.hexdigest(),
        "candidates": entries,
    }
