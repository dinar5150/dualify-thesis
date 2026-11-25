"""Compare compiled contracts with Python on a finite grid of synthetic programs."""

import itertools
import json
from collections.abc import Iterator
from textwrap import indent

import z3

from dualify.research_codegen import compile_contract
from dualify.research_contracts import Contract

ARG_TYPES = dict.fromkeys(("x", "y", "z"), "int")
VALUES = (-17, -5, -2, -1, 0, 1, 2, 5, 17)
INT_EXPRESSIONS = (
    "x", "y", "z", "-x", "abs(y)", "min(x, -y, z)", "max(x, y, -z)", "y // x",
    "x % z", "0 or (-x // y)", "x and (y % z)", "y and x or z", "x if (y % z) else (-x)",
)
BOOL_EXPRESSIONS = (
    "x > y", "not x", "x < y % z < 0", "0 > (y % z) < x", "(y % z) > 0 < x",
    "x < y < (x // z) < 0", "x < y == (x // z) != 0",
    "(x == y and y % z == 0) or (x == 0)", "not (x < y < x // z)",
)


def programs() -> Iterator[tuple[str, str]]:
    for sort, expressions in (("int", INT_EXPRESSIONS), ("bool", BOOL_EXPRESSIONS)):
        for expression in expressions:
            yield sort, f"return {expression}"
        for guard, yes, no in zip(
            BOOL_EXPRESSIONS, expressions, reversed(expressions), strict=False,
        ):
            yield sort, (
                f"if {guard}:\n    raise ValueError('guard')\n"
                f"if x < z:\n    return {yes}\nelse:\n    return {no}"
            )
            yield sort, f"return ({yes}) if {guard} else ({no})"


def same_postcondition(post: z3.BoolRef, expected: z3.BoolRef) -> bool:
    if post.eq(expected):
        return True
    # Z3 may put the integer numeral on either side of the equality.
    if (
        z3.is_eq(post) and z3.is_eq(expected)
        and post.arg(0).eq(expected.arg(1)) and post.arg(1).eq(expected.arg(0))
    ):
        return True
    solver = z3.Solver()
    solver.add(z3.Xor(post, expected))
    return solver.check() == z3.unsat


def main() -> None:
    program_count = normal_returns = exceptions = 0
    for sort, body in programs():
        source = f"def f(x: int, y: int, z: int) -> {sort}:\n" + indent(body, "    ")
        payload = compile_contract(source)
        contract = Contract(
            ARG_TYPES, sort, payload["domain_constraints"], payload["postcondition"],
        )
        namespace: dict = {}
        exec(source, namespace)  # Only the fixed synthetic programs above run here.
        function = namespace["f"]
        program_count += 1
        for inputs in itertools.product(VALUES, repeat=len(ARG_TYPES)):
            pre = contract.at(contract.pre, inputs)
            try:
                result = function(*inputs)
            except (ZeroDivisionError, ValueError):
                assert z3.is_false(pre), (source, inputs, pre)
                exceptions += 1
            else:
                post = contract.at(contract.post, inputs)
                expected = z3.simplify(contract.ret == contract.value(result))
                assert z3.is_true(pre) and same_postcondition(post, expected), (
                    source, inputs, pre, post, result,
                )
                normal_returns += 1
    print(json.dumps({
        "programs": program_count,
        "inputs_per_program": len(VALUES) ** len(ARG_TYPES),
        "checked": normal_returns + exceptions,
        "normal_returns": normal_returns,
        "exceptions": exceptions,
        "z3": z3.get_version_string(),
    }))


if __name__ == "__main__":
    main()
