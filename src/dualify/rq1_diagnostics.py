"""Evidence-based, offline diagnostics for saved RQ1 generation and evaluation."""

from __future__ import annotations

import ast
import fcntl
import json
import re
import shlex
from collections import Counter, defaultdict
from dataclasses import asdict
from pathlib import Path
from typing import Any

from dualify.fallbacks import get_fallback_extraction
from dualify.phases import p01_spec_to_logic, p02_code_to_logic
from dualify.rq1 import discover_cases
from dualify.rq1_storage import _digest, _read, slot_key


def _signature_arguments(signature: str) -> list[str] | None:
    try:
        node = ast.parse(f"def {signature}:\n    pass\n").body[0]
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return None
        return [arg.arg for arg in (*node.args.posonlyargs, *node.args.args)]
    except (SyntaxError, ValueError):
        return None


def _has_embedded_contract(source: str) -> bool:
    try:
        node = ast.parse(source).body[0]
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return False
        doc = ast.get_docstring(node) or ""
        return bool(re.search(r"(?im)^\s*(?:pre|post|inv|requires|ensures)\s*:", doc))
    except (SyntaxError, IndexError, ValueError):
        return False


def diagnose(
    root: Path, run_dir: Path, evaluation: dict[str, Any], evaluation_path: Path
) -> dict[str, Any]:
    if not (run_dir / "manifest.json").is_file():
        raise ValueError("Missing experiment manifest")
    with (run_dir / ".lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_SH | fcntl.LOCK_NB)
        return _diagnose(root, run_dir, evaluation, evaluation_path)


def _diagnose(
    root: Path, run_dir: Path, evaluation: dict[str, Any], evaluation_path: Path
) -> dict[str, Any]:
    manifest = _read(run_dir / "manifest.json")
    if (
        evaluation.get("experiment_id") != manifest.get("experiment_id")
        or evaluation.get("configuration") != manifest.get("configuration")
        or evaluation.get("selected_case_ids") != (manifest.get("plan") or {}).get("case_ids")
    ):
        raise ValueError("Evaluation does not match generation manifest")
    candidates = evaluation.get("candidates")
    if not isinstance(candidates, list):
        raise ValueError("Evaluation has no candidates list")
    cases = discover_cases(root)
    if len(candidates) != len(
        {(c["case_id"], c["channel"], c["sample_index"]) for c in candidates}
    ):
        raise ValueError("Duplicate evaluation candidate")
    expected_paths = {
        run_dir
        / "attempts"
        / slot_key(c["case_id"], c["channel"], c["sample_index"])
        / "result.json"
        for c in candidates
    }
    actual_paths = set((run_dir / "attempts").glob("*/result.json"))
    if expected_paths != actual_paths:
        raise ValueError("Evaluation is stale: terminal generation records changed")
    duplicates: dict[tuple[str, str, str], list[int]] = defaultdict(list)
    for candidate in candidates:
        key = candidate.get("final_contract_key")
        if (
            key is not None
            and candidate.get("generation_status") == "completed"
            and not candidate.get("used_fallback")
        ):
            duplicates[
                (
                    candidate["case_id"],
                    candidate["channel"],
                    json.dumps(key, sort_keys=True, ensure_ascii=False),
                )
            ].append(candidate["sample_index"])
    findings: list[dict[str, Any]] = []
    legacy_without_checksum = False
    for evaluation_row in candidates:
        identifier, channel, index = (
            evaluation_row["case_id"],
            evaluation_row["channel"],
            evaluation_row["sample_index"],
        )
        if identifier not in cases or channel not in ("spec", "code"):
            raise ValueError("Invalid case or channel in evaluation")
        case = cases[identifier]
        path = run_dir / "attempts" / slot_key(identifier, channel, index) / "result.json"
        record = _read(path)
        data = record.get("data")
        if (
            not isinstance(data, dict)
            or record.get("checksum") != _digest(data)
            or record.get("experiment_id") != manifest["experiment_id"]
            or data.get("case_id") != identifier
            or data.get("benchmark_id") != case.benchmark_id
            or data.get("channel") != channel
            or data.get("sample_index") != index
            or data.get("status") != evaluation_row.get("generation_status")
        ):
            raise ValueError(f"Invalid or mismatched generation record: {path}")
        source_checksum = evaluation_row.get("source_record_checksum")
        if source_checksum is None:
            legacy_without_checksum = True
        elif source_checksum != record["checksum"]:
            raise ValueError(f"Evaluation is stale relative to generation record: {path}")
        final = data.get("final_extraction") or {}
        trace = data.get("stage_trace") or {}
        initial = trace.get("initial") or {}
        final_validity = evaluation_row.get("final_validity") or {}
        gold = evaluation_row.get("final_gold") or {}
        errors = {
            "generation": data.get("errors", []),
            "initial_validation": initial.get("errors", []),
            "final_validation": final_validity.get("validation_errors", []),
            "initial_evaluation": evaluation_row.get("initial_error"),
            "final_evaluation": evaluation_row.get("final_error"),
        }
        config = manifest.get("configuration") or {}
        command = (
            "poetry run python scripts/diagnose_rq1.py --run-dir "
            + shlex.quote(str(run_dir))
            + " --evaluation "
            + shlex.quote(str(evaluation_path))
            + " --output-dir NEW_DIAGNOSTICS_DIR"
        )
        context = {
            "case_id": identifier,
            "benchmark_id": case.benchmark_id,
            "source_file": case.file,
            "channel": channel,
            "sample_index": index,
            "signature": case.signature,
            "input": case.informal_spec if channel == "spec" else case.function_source,
            "initial_formula": initial.get("postcondition"),
            "initial_preconditions": initial.get("domain_constraints"),
            "formula": final.get("postcondition"),
            "preconditions": final.get("domain_constraints"),
            "errors": errors,
            "api_diagnostics": data.get("diagnostics"),
            "gold_result": gold,
            "git_sha": config.get("git_sha"),
            "generation_z3_version": config.get("z3_version"),
            "evaluation_git_sha": evaluation.get("evaluation_git_sha"),
            "evaluation_z3_version": evaluation.get("evaluation_z3_version"),
            "source_record": str(path),
            "reproduction": command,
        }

        def add(
            category: str,
            classification: str,
            expected: Any,
            actual: Any,
            evidence: Any,
            _context: dict[str, Any] = context,
        ) -> None:
            findings.append(
                {
                    **_context,
                    "category": category,
                    "classification": classification,
                    "expected": expected,
                    "actual": actual,
                    "evidence": evidence,
                }
            )

        validity = evaluation_row.get("initial_validity") or {}
        if (
            validity.get("extractor_valid") is False
            or final_validity.get("extractor_valid") is False
        ):
            add(
                "invalid_dsl",
                "model_or_extraction_issue",
                "The original extractor validation accepts the contract.",
                "Original validation reported errors.",
                errors,
            )
        text = json.dumps(errors, ensure_ascii=False).lower()
        if any(
            term in text
            for term in ("unsupported", "forbidden", "not allowed", "unknown identifier")
        ):
            add(
                "unsupported_operation_or_identifier",
                "model_or_extraction_issue",
                "Formulas use operations and identifiers accepted by the original DSL.",
                "Validation or parsing reported an unsupported construct.",
                errors,
            )
        if any(
            term in text for term in ("type check", "type error", "sort mismatch", "sorts mismatch")
        ):
            add(
                "type_inconsistency",
                "suspected_translation_or_model_issue",
                "Formula types match the declared signature.",
                "A saved error indicates a type issue.",
                errors,
            )
        if gold.get("reason", "").startswith("formula_parse_error"):
            add(
                "formula_translation_error",
                "suspected_translation_or_model_issue",
                "The original scorer translates the expression.",
                gold.get("reason"),
                errors,
            )
        for relation, category in [
            ("generated_weaker", "possibly_missing_preconditions"),
            ("generated_stronger", "possibly_overly_strict_preconditions"),
        ]:
            if gold.get("pre_relation") == relation:
                add(
                    category,
                    "model_or_specification_mismatch",
                    "Generated preconditions agree with the gold preconditions.",
                    relation,
                    gold,
                )
        for relation, category in [
            ("generated_weaker", "possibly_weak_postcondition"),
            ("generated_stronger", "possibly_strong_postcondition"),
        ]:
            if gold.get("post_relation") == relation:
                add(
                    category,
                    "model_or_specification_mismatch",
                    "Generated postcondition agrees with gold on the common domain.",
                    relation,
                    gold,
                )
        if evaluation_row.get("vacuous"):
            add(
                "vacuous_postcondition",
                "model_or_extraction_issue",
                "The contract constrains the return value.",
                "The final formula is ret == ret.",
                final,
            )
        if evaluation_row.get("repair_attempted") and not final_validity.get(
            "extractor_valid", False
        ):
            add(
                "repair_failure",
                "model_or_extraction_issue",
                "Repair returns a contract accepted by original validation.",
                "Final contract is invalid or unavailable after a repair attempt.",
                trace,
            )
        duplicate_key = evaluation_row.get("final_contract_key")
        if duplicate_key is not None:
            group = duplicates.get(
                (
                    identifier,
                    channel,
                    json.dumps(duplicate_key, sort_keys=True, ensure_ascii=False),
                ),
                [],
            )
            if len(group) > 1:
                add(
                    "repeated_identical_candidates",
                    "observation",
                    "Independent requests do not reuse a prior response; "
                    "outputs may still coincide.",
                    f"The same normalized contract occurs in {len(group)} samples.",
                    group,
                )
        reason = str(gold.get("reason", ""))
        if reason.startswith("solver_unknown") or "undetermined" in (
            gold.get("pre_relation"),
            gold.get("post_relation"),
        ):
            add(
                "solver_unknown",
                "known_solver_limitation",
                "The solver establishes the needed relation or reports it inconclusive.",
                "The original scorer reports an unknown or undetermined result.",
                gold,
            )
        for needle, category in [
            ("timeout", "reported_timeout"),
            ("incomplete", "reported_incomplete_theory"),
        ]:
            if needle in (text + " " + reason.lower()):
                add(
                    category,
                    "reported_diagnostic",
                    "The solver or provider completes the operation.",
                    f"Saved diagnostics mention {needle}.",
                    {"errors": errors, "gold": gold},
                )
        if reason in ("vacuous_equivalence", "low_confidence_parse"):
            add(
                "unusual_proof_outcome",
                "observation",
                "Inspect the underlying proof reason.",
                reason,
                gold,
            )
        phase = p01_spec_to_logic if channel == "spec" else p02_code_to_logic
        expected_args = _signature_arguments(case.signature)
        actual_args = phase._extract_signature_args(case.signature)
        if expected_args is not None and expected_args != actual_args:
            add(
                "signature_argument_parsing",
                "confirmed_implementation_bug",
                expected_args,
                actual_args,
                {"signature": case.signature, "method": "_extract_signature_args splits on commas"},
            )
        formulas = json.dumps({"initial": initial, "final": final}, ensure_ascii=False)
        if "__" in formulas:
            add(
                "unsafe_expression_handling",
                "suspected_implementation_risk",
                "Untrusted expressions are safely rejected before evaluation.",
                "Formula contains a double-underscore token; original code uses Python eval.",
                {
                    "formulas": formulas,
                    "location": "src/dualify/phases/p03_smt_checking.py:_safe_eval",
                },
            )
        if data.get("used_fallback"):
            try:
                expected_fallback = asdict(get_fallback_extraction(case.benchmark_id))
            except ValueError:
                expected_fallback = None
            if expected_fallback != final:
                add(
                    "fallback_mismatch",
                    "suspected_implementation_bug",
                    expected_fallback,
                    final,
                    {"used_fallback": True},
                )
            else:
                add(
                    "original_fallback",
                    "observation",
                    "Report fallback provenance separately.",
                    "The original deterministic fallback was used.",
                    final,
                )
        api = data.get("diagnostics") or {}
        if data.get("errors") or api.get("provider_failures"):
            add(
                "provider_failure",
                "observed_api_failure",
                "Provider calls return successfully or errors are visible.",
                "The saved attempt contains API errors or HTTP failure responses.",
                {"errors": data.get("errors"), "provider_failures": api.get("provider_failures")},
            )
        if data.get("status") == "error" and not data.get("errors"):
            add(
                "missing_error_details",
                "suspected_implementation_issue",
                "Failed attempts retain their observable error details.",
                "The attempt is marked as an error but has no recorded error messages.",
                {"status": data.get("status"), "diagnostics": api},
            )
        if channel == "code" and _has_embedded_contract(case.function_source):
            add(
                "channel_independence",
                "suspected_evaluation_limitation",
                "Interpret the implementation channel with its available context documented.",
                "The code supplied to the extractor contains a contract-like docstring.",
                {
                    "source_file": case.file,
                    "qualification": "Not proof of gold or training leakage.",
                },
            )
    counts = Counter(f["category"] for f in findings)
    return {
        "experiment_id": manifest["experiment_id"],
        "generation_git_sha": (manifest.get("configuration") or {}).get("git_sha"),
        "generation_z3_version": (manifest.get("configuration") or {}).get("z3_version"),
        "evaluation_z3_version": evaluation.get("evaluation_z3_version"),
        "evaluated_candidates": len(candidates),
        "findings": findings,
        "counts": dict(sorted(counts.items())),
        "limitations": [
            "Solver unknown is inconclusive and is not proof of a Z3 defect.",
            "Timeout or incomplete-theory causes are listed only if recorded; "
            "unknown alone has no cause.",
            "Original solver uses Python eval; this is a risk observation, "
            "not a demonstrated exploit.",
            "Original client can hide recovered errors and does not retain "
            "all provider response bodies.",
            "Docstrings and detailed informal specs can limit channel independence; "
            "this does not prove gold or training-data leakage.",
            "The six-case dev selection is a debugging aid, not a representative research sample.",
            *(
                ["Evaluation lacks per-record checksums; regenerate it to verify freshness."]
                if legacy_without_checksum
                else []
            ),
        ],
    }
