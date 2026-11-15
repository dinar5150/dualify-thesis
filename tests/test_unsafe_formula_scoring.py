"""Rejected model formulas must not execute Python comprehensions during scoring."""

from __future__ import annotations

import pytest
import z3

from dualify.gold_scoring import GoldContract, score_extraction_against_gold
from dualify.phases.p03_smt_checking import CaseSpec, _safe_eval
from dualify.relation import PARSE_ERROR, contract_relation
from dualify.rq1_sampling import GoldScoreCache, _initial_score
from dualify.types import ExtractionResult


def test_invalid_initial_candidate_skips_gold_scoring() -> None:
    """The original RQ1 OOM occurred before the candidate was labeled invalid."""
    formula = "ret == Sum([x for x in numbers])"
    errors = ["postcondition unsupported function calls: Sum"]
    case = {
        "spec_to_logic": {
            "extraction_trace": {
                "initial": {
                    "postcondition": formula,
                    "domain_constraints": [],
                    "errors": errors,
                }
            }
        }
    }
    # An empty gold cache would raise if scoring were mistakenly attempted.
    cache = GoldScoreCache({})
    result = _initial_score(case, "spec_to_logic", {}, cache=cache)

    assert result["outcome"] == "invalid"
    assert result["errors"] == errors
    assert result["postcondition"] == formula
    assert "gold" not in result
    assert cache.misses == 0
    assert cache.hits == 0


@pytest.mark.parametrize(
    "formula, node_type",
    [
        ("ret == Sum([x for x in numbers])", "ListComp"),
        ("ret == Sum(x for x in numbers)", "GeneratorExp"),
        ("ret == (lambda x: x)(1)", "Lambda"),
    ],
)
def test_shared_evaluator_rejects_unsafe_ast_before_execution(
    formula: str, node_type: str
) -> None:
    class NoIteration:
        def __iter__(self):
            raise AssertionError("An unsafe formula was executed")

    with pytest.raises(ValueError, match=f"unsupported AST node: {node_type}"):
        _safe_eval(formula, {"numbers": NoIteration(), "ret": 0}, "average")


def test_gold_scoring_and_relation_reject_unsafe_comprehension() -> None:
    case_spec = CaseSpec(
        benchmark_id="average",
        arg_types={"numbers": "List[int]"},
        return_type="int",
    )
    gold = GoldContract(
        benchmark_id="average",
        qualname="average",
        in_fragment=True,
        args=["numbers"],
        arg_types={"numbers": "List[int]"},
        return_type="int",
        domain_constraints=[],
        postcondition="ret == 0",
    )
    generated = ExtractionResult(
        benchmark_id="average",
        args=["numbers"],
        return_type="int",
        domain_constraints=[],
        postcondition="ret == Sum([x for x in numbers])",
        confidence="low",
        notes="",
    )
    reference = ExtractionResult(
        benchmark_id="average",
        args=["numbers"],
        return_type="int",
        domain_constraints=[],
        postcondition="ret == 0",
        confidence="gold",
        notes="",
    )
    score = score_extraction_against_gold(
        case_spec=case_spec, gold=gold, extraction=generated
    )
    assert not score.contract_equivalent
    assert "unsupported AST node: ListComp" in score.reason
    assert contract_relation(case_spec, reference, generated) == {
        "pre": PARSE_ERROR,
        "post": PARSE_ERROR,
    }


def test_shared_evaluator_preserves_supported_formula() -> None:
    scope = {
        "ret": z3.Int("ret"),
        "numbers": z3.Const("numbers", z3.SeqSort(z3.IntSort())),
    }
    assert _safe_eval("ret == Length(numbers)", scope, "example") is not None
