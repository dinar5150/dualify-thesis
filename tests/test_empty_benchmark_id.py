"""Regression tests for empty benchmark IDs in extraction-side Z3 validation."""

import ast

from dualify.phases.p03_smt_checking import (
    _canonicalize_expression,
    extraction_parseable,
)


def test_empty_benchmark_id_preserves_nested_calls() -> None:
    expression = (
        "ret == If(Contains(histo, Unit(1)), histo[1], 0) "
        "* If(Contains(histo, Unit(3)), histo[3], 0)"
    )
    rewritten = _canonicalize_expression(expression, "")
    ast.parse(rewritten, mode="eval")
    assert "If(" in rewritten
    assert "Contains(" in rewritten
    assert "Unit(" in rewritten
    assert "Ifret" not in rewritten


def test_extraction_typecheck_accepts_valid_if_expression() -> None:
    diagnostics: list[str] = []
    assert extraction_parseable(
        {"n": "int"},
        "int",
        [],
        "ret == If(n > 0, n, 0)",
        error_details=diagnostics,
    ), diagnostics


def test_extraction_typecheck_accepts_length_postcondition() -> None:
    diagnostics: list[str] = []
    assert extraction_parseable(
        {"items": "List[str]"},
        "List[str]",
        [],
        "Length(ret) == 2 * Length(items)",
        error_details=diagnostics,
    ), diagnostics
