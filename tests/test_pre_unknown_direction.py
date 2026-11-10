"""Precondition direction must not be guessed from Z3 unknown."""

from __future__ import annotations

import z3

from dualify.phases import p03_smt_checking as smt
from dualify.types import ExtractionResult


def _ex(pre: str) -> ExtractionResult:
    return ExtractionResult(
        benchmark_id="pre_direction",
        args=["x"],
        return_type="int",
        domain_constraints=[pre],
        postcondition="ret == x",
        confidence="high",
        notes="",
    )


def test_pre_xor_sat_unknown_direction_is_inconclusive(monkeypatch) -> None:
    original = smt._check_with_status
    count = 0

    def check(solver: z3.Solver) -> z3.CheckSatResult:
        nonlocal count
        count += 1
        if count == 2:
            return z3.unknown
        return original(solver)

    monkeypatch.setattr(smt, "_check_with_status", check)
    case = smt.CaseSpec("pre_direction", {"x": "int"}, "int")
    result = smt.check_equivalence(case, _ex("x == 0"), _ex("x == 1"))
    assert result.reason == "solver_unknown"
    assert result.well_formedness == "solver_unknown_pre_direction"
    assert result.diagnostics["solver_status"]["pre_mismatch_check"] == "sat"
    assert result.diagnostics["solver_status"]["pre_spec_implies_pre_code"] == "unknown"


def test_pre_xor_sat_one_valid_implication_is_enough(monkeypatch) -> None:
    original = smt._check_with_status
    count = 0

    def check(solver: z3.Solver) -> z3.CheckSatResult:
        nonlocal count
        count += 1
        if count == 2:
            return z3.unknown
        return original(solver)

    monkeypatch.setattr(smt, "_check_with_status", check)
    case = smt.CaseSpec("pre_direction", {"x": "int"}, "int")
    result = smt.check_equivalence(case, _ex("x >= 0"), _ex("x >= 1"))
    assert result.reason == "case_pre_code"
    assert result.diagnostics["solver_status"]["pre_code_implies_pre_spec"] == "unsat"
