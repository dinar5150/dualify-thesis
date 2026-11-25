import pytest

from dualify.phases.p01_spec_to_logic import extract_spec_logic
from dualify.phases.p02_code_to_logic import extract_code_logic
from scripts.research.pipeline_audit import Variant, validation_variant


class FormulaClient:
    def __init__(self, formula: str, domain: tuple[str, ...] = ()) -> None:
        self.formula = formula
        self.domain = domain
        self.calls = 0

    def generate_json(self, prompt: str, temperature: float = 0.0) -> dict:
        self.calls += 1
        return {"domain_constraints": list(self.domain), "postcondition": self.formula}

    def healthcheck(self) -> None:
        return None


@pytest.mark.parametrize("channel", ["spec", "code"])
@pytest.mark.parametrize(
    ("variant", "expected_calls"),
    [("baseline", 3), ("benchmark_id", 1), ("literals", 3), ("both", 1)],
)
def test_well_typed_initial_conditional(
    channel: str, variant: Variant, expected_calls: int,
) -> None:
    formula = "ret == If(x > 0, 1, 0)"
    client = FormulaClient(formula)
    with validation_variant(variant):
        if channel == "spec":
            extraction = extract_spec_logic(
                client, "indicator", "indicator(x: int) -> int",
                "Return 1 if x is positive and 0 otherwise.", "int",
                arg_types={"x": "int"},
            )
        else:
            extraction = extract_code_logic(
                client, "indicator", "indicator(x: int) -> int",
                "def indicator(x: int) -> int:\n    return 1 if x > 0 else 0",
                "int", arg_types={"x": "int"},
            )
    assert client.calls == expected_calls
    assert extraction.degraded == (expected_calls == 3)
    assert extraction.postcondition == (formula if expected_calls == 1 else "ret == ret")


@pytest.mark.parametrize(
    ("variant", "expected_calls"),
    [("baseline", 3), ("benchmark_id", 3), ("literals", 3), ("both", 1)],
)
def test_string_character_comparison_needs_both_corrections(
    variant: Variant, expected_calls: int,
) -> None:
    client = FormulaClient("ret == If(And(Length(x) > 0, x[0] == 'L'), 1, 0)")
    with validation_variant(variant):
        extraction = extract_spec_logic(
            client, "indicator", "indicator(x: str) -> int",
            "Return 1 if x begins with L and 0 otherwise.", "int",
            arg_types={"x": "str"},
        )
    assert client.calls == expected_calls
    assert extraction.postcondition == (
        "ret == If(And(Length(x) > 0, x[0] == Char('L')), 1, 0)"
        if expected_calls == 1 else "ret == ret"
    )


@pytest.mark.parametrize(
    ("variant", "domain", "expected_calls"),
    [
        ("both", "bus_id > 0", 3),
        ("both_with_nonzero_domain", "bus_id > 0", 1),
        ("both_with_nonzero_domain", "Or(bus_id > 0, min_time < 0)", 3),
    ],
)
def test_modulo_guard_respects_unconditional_domain_constraint(
    variant: Variant, domain: str, expected_calls: int,
) -> None:
    post = "And(ret >= min_time, ret % bus_id == 0, ret - min_time < bus_id)"
    client = FormulaClient(post, (domain,))
    with validation_variant(variant):
        extraction = extract_code_logic(
            client, "next_departure", "next_departure(bus_id: int, min_time: int) -> int",
            "def next_departure(bus_id, min_time):\n    return min_time + (-min_time % bus_id)",
            "int", arg_types={"bus_id": "int", "min_time": "int"},
        )
    assert client.calls == expected_calls
    if expected_calls == 1:
        assert extraction.postcondition == post
        assert extraction.domain_constraints == [domain]
