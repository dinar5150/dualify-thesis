import inspect
import textwrap
from itertools import product

import pytest

from dualify.research_codegen import UnsupportedSource, compile_contract
from dualify.research_contracts import Contract, find_witness, relation


def test_compiles_guards_raises_and_nested_returns() -> None:
    source = textwrap.dedent("""\
        def tier(score: int, threshold: int) -> int:
            if threshold < 0:
                raise ValueError("threshold")
            if score < threshold:
                if score < 0:
                    return 0
                return score + 1
            return score - threshold
        """)
    args = {"score": "int", "threshold": "int"}
    generated = compile_contract(source)
    expected = Contract(
        args, "int", ["threshold >= 0"],
        "ret == If(score >= threshold, score - threshold, If(score < 0, 0, score + 1))",
    )

    contract = Contract(args, "int", generated["domain_constraints"], generated["postcondition"])
    assert relation(contract, expected) == ("unsat", "unsat")


def test_uses_python_signed_division_and_remainder() -> None:
    source = textwrap.dedent("""\
        def alternate(value: int, divisor: int, quotient: int) -> int:
            if quotient:
                return value // divisor
            return value % divisor
        """)
    args = {"value": "int", "divisor": "int", "quotient": "int"}
    corrected = compile_contract(source)
    raw = compile_contract(source, python_division=False)
    candidate = Contract(args, "int", corrected["domain_constraints"], corrected["postcondition"])
    raw_candidate = Contract(args, "int", raw["domain_constraints"], raw["postcondition"])
    examples = (
        ((7, -3, 1), -3), ((-7, 3, 1), -3), ((-7, -3, 1), 2), ((9, 3, 1), 3),
        ((7, -3, 0), -2), ((-7, 3, 0), 2), ((-7, -3, 0), -1), ((9, 3, 0), 0),
        ((7, 0, 1), None), ((7, 0, 0), None),
    )
    assert find_witness(candidate, examples) is None
    assert find_witness(raw_candidate, examples) == {
        "args": {"value": 7, "divisor": -3, "quotient": 1},
        "kind": "rejects_return",
        "ret": -3,
    }


def test_excludes_division_by_zero_only_when_evaluated() -> None:
    def in_band(limit: int, offset: int, divisor: int) -> bool:
        return (limit > 0 and 1 < offset < 30 // divisor) or offset == -1

    source = textwrap.dedent(inspect.getsource(in_band))
    args = {"limit": "int", "offset": "int", "divisor": "int"}
    payload = compile_contract(source)
    contract = Contract(args, "bool", payload["domain_constraints"], payload["postcondition"])
    inputs = list(product((-2, 0, 1), (-1, 1, 2, 17), (-2, 0, 2)))
    examples = []
    for values in inputs:
        try:
            expected = in_band(*values)
        except ZeroDivisionError:
            expected = None
        examples.append((values, expected))
    assert find_witness(contract, examples) is None


def test_compiles_pure_builtins_and_conditional_expression() -> None:
    source = "def band(x: int) -> int:\n    return min(3, abs(x)) if x else max(0, -x, 7)"
    args = {"x": "int"}
    payload = compile_contract(source)
    contract = Contract(args, "int", payload["domain_constraints"], payload["postcondition"])
    assert find_witness(contract, (((-8,), 3), ((-2,), 2), ((0,), 7), ((1,), 1))) is None


@pytest.mark.parametrize("source", [
    "def f(x: int) -> int:\n    print(x)\n    return x",
    "def f(x: int) -> int:\n    for _ in range(x):\n        return x\n    return 0",
    "def f(x: int) -> int:\n    return x / 2",
    "def f(x: int) -> int:\n    return globals()['x']",
    "def f(x: int) -> int:\n    if x > 0:\n        return x",
    "def f(x: int) -> int:\n    raise ValueError(print(x))",
    "def f(x: int) -> bool:\n    return x",
    "def f(x: int = 0) -> int:\n    return x",
    "def f(x: int, x: int) -> int:\n    return x",
    "def f(x) -> int:\n    return x",
    "def f(ret: int) -> int:\n    return ret",
    "def f(min: int) -> int:\n    return min(1, 2)",
    "@external\ndef f(x: int) -> int:\n    return x",
    "min = print\ndef f(x: int) -> int:\n    return min(x, 5)",
])
def test_abstains_outside_the_supported_fragment(source: str) -> None:
    with pytest.raises(UnsupportedSource):
        compile_contract(source)
