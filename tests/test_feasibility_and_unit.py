"""Regressions for Z3 literal conversion and contract feasibility (offline)."""

from __future__ import annotations

import pytest
import z3

from dualify.phases.p01_spec_to_logic import _typecheck_errors as spec_validation
from dualify.phases.p02_code_to_logic import _typecheck_errors as code_validation
from dualify.phases.p03_smt_checking import (
    _make_var,
    _safe_eval,
    extraction_feasibility,
    extraction_parseable,
)


@pytest.mark.parametrize("literal", [1, 3])
def test_unit_accepts_python_integer_literals(literal: int) -> None:
    expr = _safe_eval(f"Contains(histo, Unit({literal}))", {
        "histo": _make_var("histo", "HistogramOfDeltas"),
    }, "")
    assert z3.is_bool(expr)
    solver = z3.Solver()
    solver.add(expr)
    assert solver.check() == z3.sat


def test_unit_represents_sequence_membership_not_dictionary_key_lookup() -> None:
    # HistogramOfDeltas is currently encoded as a Z3 sequence, not a Python dict.
    # This checks the helper's actual semantics without claiming key-lookup equivalence.
    for element, expected in [(1, z3.sat), (2, z3.unsat)]:
        expr = _safe_eval(f"Contains(Unit({element}), Unit(1))", {}, "")
        solver = z3.Solver()
        solver.add(expr)
        assert solver.check() == expected


def test_original_compute_result_expression_is_parseable() -> None:
    details: list[str] = []
    formula = (
        "ret == If(Contains(histo, Unit(1)), histo[1], 0) * "
        "If(Contains(histo, Unit(3)), histo[3], 0)"
    )
    assert extraction_parseable(
        {"histo": "HistogramOfDeltas"}, "int", [], formula,
        error_details=details,
    ), details


def test_rejects_unsatisfiable_universal_and_bounds() -> None:
    details: list[str] = []
    formula = (
        "And(Length(ret) == n, ForAll([i], "
        "And(0 <= i, i < Length(ret), ret[i] % 2 == 0)))"
    )
    assert extraction_parseable(
        {"n": "int"}, "List[int]", ["n >= 0"], formula,
        error_details=details,
    ), details
    assert extraction_feasibility(
        {"n": "int"}, "List[int]", ["n >= 0"], formula,
    ).status == "unsat_contract"


def test_accepts_guarded_quantifier() -> None:
    details: list[str] = []
    formula = (
        "And(Length(ret) == n, ForAll([i], "
        "Implies(And(0 <= i, i < Length(ret)), ret[i] % 2 == 0)))"
    )
    assert extraction_parseable(
        {"n": "int"}, "List[int]", ["n >= 0"], formula,
        error_details=details,
    ), details
    assert extraction_feasibility(
        {"n": "int"}, "List[int]", ["n >= 0"], formula,
    ).status == "sat"


def test_rejects_contradictory_preconditions() -> None:
    details: list[str] = []
    assert extraction_parseable(
        {"n": "int"}, "int", ["n > 0", "n < 0"], "ret == n",
        error_details=details,
    ), details
    assert extraction_feasibility(
        {"n": "int"}, "int", ["n > 0", "n < 0"], "ret == n",
    ).status == "unsat_pre"


def test_rejects_simple_postcondition_contradiction() -> None:
    details: list[str] = []
    assert extraction_parseable(
        {"x": "int"}, "int", [], "And(ret == 0, ret == 1)",
        error_details=details,
    ), details
    assert extraction_feasibility(
        {"x": "int"}, "int", [], "And(ret == 0, ret == 1)",
    ).status == "unsat_contract"


@pytest.mark.parametrize("validation", [spec_validation, code_validation])
def test_unsatisfiable_contract_provides_repair_error(validation) -> None:
    details: list[str] = []
    errors = validation([], "And(ret == 0, ret == 1)", {"x": "int"}, "int", diagnostics=details)
    assert errors == ["postcondition/constraints are unsatisfiable"]
    assert any("unsatisfiable contract" in d for d in details)


@pytest.mark.parametrize("validation", [spec_validation, code_validation])
def test_previously_detected_type_errors_still_rejected(validation) -> None:
    details: list[str] = []
    errors = validation([], "ret == Length(x)", {"x": "int"}, "int", diagnostics=details)
    assert errors == ["postcondition/constraints fail Z3 type check"]
    assert details


def test_unknown_satisfiability_is_recorded_but_not_rejected(monkeypatch) -> None:
    """A timeout is not proof that the contract is inconsistent."""
    from dualify.phases import p03_smt_checking as smt

    class UnknownSolver:
        def set(self, *args, **kwargs) -> None:
            pass

        def add(self, *args) -> None:
            pass

        def check(self):
            return z3.unknown

        def reason_unknown(self) -> str:
            return "timeout"

    monkeypatch.setattr(smt.z3, "Solver", UnknownSolver)
    result = smt._contract_feasibility([], True)
    assert result.status == "unknown"
    assert result.reason == "timeout"
