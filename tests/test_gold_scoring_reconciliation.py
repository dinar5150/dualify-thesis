"""Sound evidence from either SMT checking path must be reflected consistently."""

from __future__ import annotations

from dualify import gold_scoring
from dualify.phases.p03_smt_checking import CaseSpec
from dualify.types import ExtractionResult, SmtResult


def _case_and_gold():
    gold = gold_scoring.GoldContract(
        benchmark_id="toy::x", qualname="x", in_fragment=True,
        args=["x"], arg_types={"x": "int"}, return_type="int",
        domain_constraints=[], postcondition="ret == x",
    )
    case = CaseSpec(benchmark_id="x", arg_types={"x": "int"}, return_type="int")
    candidate = ExtractionResult(
        benchmark_id="x", args=["x"], return_type="int",
        domain_constraints=[], postcondition="ret == x + 0",
        confidence="high", notes="",
    )
    return case, gold, candidate


def _score(monkeypatch, *, check, pre="equivalent", post="undetermined"):
    monkeypatch.setattr(gold_scoring, "check_equivalence", lambda *args: check)
    monkeypatch.setattr(gold_scoring, "contract_relation", lambda *args: {"pre": pre, "post": post})
    case, gold, candidate = _case_and_gold()
    return gold_scoring.score_extraction_against_gold(
        case_spec=case, gold=gold, extraction=candidate
    )


def test_equivalence_proof_overrides_undetermined_relation(monkeypatch):
    check = SmtResult("x", True, "equivalent_no_mismatch", None)
    result = _score(monkeypatch, check=check)
    assert result.contract_equivalent
    assert result.post_relation == "equivalent"


def test_two_proved_implications_rescue_xor_unknown(monkeypatch):
    check = SmtResult("x", False, "solver_unknown", None, diagnostics={"post_well_formedness": "ok"})
    result = _score(monkeypatch, check=check, post="equivalent")
    assert result.contract_equivalent
    assert result.reason == "equivalent_via_implications"


def test_unknown_alone_is_never_success(monkeypatch):
    check = SmtResult("x", False, "solver_unknown", None, diagnostics={"post_well_formedness": "ok"})
    result = _score(monkeypatch, check=check)
    assert not result.contract_equivalent
    assert result.reason == "solver_unknown"


def test_proved_directional_difference_overrides_unknown(monkeypatch):
    check = SmtResult("x", False, "solver_unknown", None, diagnostics={"post_well_formedness": "ok"})
    result = _score(monkeypatch, check=check, post="generated_stronger")
    assert not result.contract_equivalent
    assert result.reason == "non_equivalent_via_implications"


def test_conflicting_definite_proofs_are_reported(monkeypatch):
    check = SmtResult("x", True, "equivalent_no_mismatch", None)
    result = _score(monkeypatch, check=check, post="generated_stronger")
    assert not result.contract_equivalent
    assert result.reason == "oracle_conflict"


def test_xor_sat_and_one_valid_implication_proves_generated_stronger(monkeypatch):
    check = SmtResult(
        "x", False, "solver_unknown", None,
        diagnostics={
            "post_well_formedness": "ok",
            "solver_status": {
                "post_mismatch_check": "sat",
                "spec_post_implies_code_post": "unknown",
                "code_post_implies_spec_post": "unsat",
            },
        },
    )
    result = _score(monkeypatch, check=check, post="undetermined")
    assert not result.contract_equivalent
    assert result.post_relation == "generated_stronger"
    assert result.reason == "non_equivalent_via_implications"


def test_xor_sat_without_direction_proves_non_equivalence(monkeypatch):
    check = SmtResult(
        "x", False, "solver_unknown", None,
        diagnostics={
            "post_well_formedness": "ok",
            "solver_status": {
                "post_mismatch_check": "sat",
                "spec_post_implies_code_post": "unknown",
                "code_post_implies_spec_post": "unknown",
            },
        },
    )
    result = _score(monkeypatch, check=check)
    assert not result.contract_equivalent
    assert result.reason == "non_equivalent_via_xor"


def test_conflicting_xor_and_implications_never_pass(monkeypatch):
    check = SmtResult(
        "x", False, "solver_unknown", None,
        diagnostics={
            "post_well_formedness": "ok",
            "solver_status": {"post_mismatch_check": "sat"},
        },
    )
    result = _score(monkeypatch, check=check, post="equivalent")
    assert not result.contract_equivalent
    assert result.reason == "oracle_conflict"
