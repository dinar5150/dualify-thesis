"""Controlled judge fixtures. Pair labels are available outside judge prompts only."""

from contract_cases import CASES

# (case index, correct encoding, incorrect encoding, why the latter fails)
PAIRS = (
    (0, (["days >= 0"], "ret == max(0, min(9, 3 * (days - 2)))"),
     (["days >= 0"], "ret == If(days <= 2, 0, 3 * (days - 2))"), "missing cap"),
    (1, (["lower <= upper"], "ret == max(0, lower - value, value - upper)"),
     (["lower < upper"], "ret == max(0, lower - value, value - upper)"), "narrow pre"),
    (2, (["step != 0"], "ret == If(step < 0, -value / -step, value / step)"),
     (["step != 0"], "ret == value / step"), "negative divisor semantics"),
    (3, (["credit >= 0", "bill >= 0"],
          "ret == If(credit == bill, bill + 1, min(credit, bill))"),
     (["credit >= 0", "bill >= 0"], "ret == ret"), "tautological post"),
    (4, (["width > 0"], "ret == And(offset < width, -width <= offset)"),
     (["width > 0", "width <= 0"], "ret == And(offset < width, -width <= offset)"),
     "vacuous pre"),
    (7, ([], "ret == And(min(a, c) < b, b < max(a, c))"),
     ([], "ret == Or(And(a <= b, b < c), And(c <= b, b < a))"), "boundary error"),
)


def describe(pair: tuple[list[str], str]) -> dict:
    return {"domain_constraints": pair[0], "postcondition": pair[1]}


def source_for(index: int, channel: str) -> str:
    case = CASES[index]
    return case.signature + "\n" + (case.prose if channel == "spec" else case.source)
