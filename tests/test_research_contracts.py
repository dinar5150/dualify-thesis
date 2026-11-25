import pytest

from dualify.research_contracts import Contract, FormulaError, find_witness, relation


def test_rejects_missing_negative_divisor_rounding():
    candidate = Contract({"value": "int", "step": "int"}, "int", ["step != 0"],
                         "ret == value / step")
    expected = Contract({"value": "int", "step": "int"}, "int", ["step != 0"],
                        "ret == If(step > 0, value / step, -value / -step)")
    assert relation(candidate, expected) == ("unsat", "sat")
    assert find_witness(candidate, [((5, -2), -3)]) == {
        "args": {"value": 5, "step": -2}, "kind": "rejects_return", "ret": -3,
    }


def test_distinguishes_vacuity_and_underconstraint():
    vacuous = Contract({"x": "int"}, "int", ["x > 0", "x < 0"], "ret == x")
    assert find_witness(vacuous, [((1,), 1)]) == {
        "args": {"x": 1}, "kind": "rejects_input", "ret": None,
    }
    weak = Contract({"x": "int"}, "int", [], "ret == ret")
    witness = find_witness(weak, [((1,), 1)])
    assert witness and witness["kind"] == "admits_wrong_return" and witness["ret"] != 1


@pytest.mark.parametrize("post", ["ret + x", "ret.__class__ == x", "Unknown(x) == ret"])
def test_rejects_non_boolean_and_out_of_fragment_formulas(post):
    with pytest.raises(FormulaError):
        Contract({"x": "int"}, "int", [], post)


def test_precondition_cannot_depend_on_return_value():
    with pytest.raises(FormulaError):
        Contract({"x": "int"}, "int", ["ret == 2"], "ret == x")

@pytest.mark.parametrize("post", ["Not(ret == x, True)", "Implies(True, ret == x, False)"])
def test_logical_calls_reject_extra_operands(post):
    with pytest.raises(FormulaError, match="requires"):
        Contract({"x": "int"}, "int", [], post)


def test_underspecified_division_cannot_supply_a_definite_ground_witness():
    candidate = Contract({"x": "int"}, "int", [], "ret == 1 / x")
    assert find_witness(candidate, [((0,), 0)]) is None
