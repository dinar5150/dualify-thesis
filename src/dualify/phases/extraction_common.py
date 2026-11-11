"""Small shared helpers for the spec and code extraction phases."""

from collections.abc import Mapping
from typing import Any

from dualify.phases.p03_smt_checking import extraction_feasibility, extraction_parseable

_REPAIR_FIELDS = (
    "args", "return_type", "domain_constraints", "postcondition", "confidence", "notes",
)


def repair_prompt_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Only send contract fields to the LLM, never traces or pipeline metadata."""
    return {key: payload[key] for key in _REPAIR_FIELDS}


def trace_entry(
    payload: Mapping[str, Any], errors: list[str], diagnostics: list[str]
) -> dict[str, Any]:
    return {
        "domain_constraints": list(payload["domain_constraints"]),
        "postcondition": payload["postcondition"],
        "errors": list(errors),
        "z3_diagnostics": list(diagnostics),
    }


def typecheck_errors(
    domain_constraints: list[str],
    postcondition: str,
    arg_types: dict[str, str] | None,
    return_type: str,
    *,
    diagnostics: list[str] | None = None,
) -> list[str]:
    """Validate parsing and, separately, reject proven-unsatisfiable contracts."""
    if not arg_types:
        return []
    if not extraction_parseable(
        arg_types, return_type, domain_constraints, postcondition,
        error_details=diagnostics,
    ):
        return ["postcondition/constraints fail Z3 type check"]

    outcome = extraction_feasibility(arg_types, return_type, domain_constraints, postcondition)
    if outcome.status == "unsat_pre":
        if diagnostics is not None:
            diagnostics.append("unsatisfiable preconditions (Z3: unsat)")
        return ["domain constraints are unsatisfiable"]
    if outcome.status == "unsat_contract":
        if diagnostics is not None:
            diagnostics.append("unsatisfiable contract (Z3: unsat)")
        return ["postcondition/constraints are unsatisfiable"]
    if outcome.status == "unknown" and diagnostics is not None:
        diagnostics.append(f"satisfiability unknown (Z3: unknown; {outcome.reason})")
    if outcome.status == "invalid":
        if diagnostics is not None:
            diagnostics.append(outcome.reason)
        return ["postcondition/constraints fail Z3 type check"]
    return []
