"""New, independently specified scalar cases for the post-freeze experiment."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Case:
    name: str
    args: str
    prose: str
    body: str
    pre: str
    post: str
    examples: tuple[tuple[tuple[int, ...], int | None], ...]
    return_type: str = "int"

    @property
    def signature(self) -> str:
        args = ", ".join(f"{arg}: int" for arg in self.args.split())
        return f"def {self.name}({args}) -> {self.return_type}"

    @property
    def source(self) -> str:
        return f"{self.signature}:\n" + "".join(
            f"    {line}\n" for line in self.body.splitlines()
        )


CASES = (
    Case("late_fee", "days",
         "Reject negative day counts. Charge nothing for the first two days, "
         "then charge three units per additional day, up to a total of nine units.",
         "if days < 0:\n    raise ValueError()\n"
         "return min(9, 3 * max(0, days - 2))",
         "days >= 0", "ret == If(days <= 2, 0, If(days <= 5, 3*(days-2), 9))",
         (((-1,), None), ((0,), 0), ((2,), 0), ((3,), 3), ((5,), 9), ((12,), 9))),
    Case("band_distance", "value lower upper",
         "Reject reversed bounds. Return zero inside the closed interval and "
         "otherwise the distance to its nearest endpoint.",
         "if lower > upper:\n    raise ValueError()\n"
         "return max(lower - value, 0, value - upper)",
         "lower <= upper", "ret == If(value < lower, lower-value, "
         "If(value > upper, value-upper, 0))",
         (((0, 2, 1), None), ((-4, -2, 2), 2), ((2, 2, 2), 0), ((4, 2, 3), 1))),
    Case("signed_bucket", "value step",
         "Reject a zero step. Return the mathematical floor of the quotient of "
         "value by step. A negative step is allowed.",
         "if step == 0:\n    raise ValueError()\nreturn value // step",
         "step != 0", "ret == If(step > 0, value / step, (-value) / (-step))",
         (((2, 0), None), ((5, -2), -3), ((-5, 2), -3), ((-5, -2), 2), ((4, 2), 2))),
    Case("bounded_payment", "credit bill",
         "Reject a negative credit or bill. Pay the smaller of the two amounts. "
         "When credit and bill agree, add a bonus of one to the payment.",
         "if credit < 0 or bill < 0:\n    raise ValueError()\n"
         "if credit == bill:\n    return bill + 1\nreturn min(credit, bill)",
         "And(credit >= 0, bill >= 0)",
         "ret == If(credit == bill, bill+1, If(credit <= bill, credit, bill))",
         (((-1, 2), None), ((2, -1), None), ((0, 0), 1), ((1, 3), 1), ((9, 3), 3))),
    Case("index_class", "offset width",
         "Reject nonpositive width. Report whether offset is a valid Python "
         "index for a sequence of that width, including negative indices.",
         "if width <= 0:\n    raise ValueError()\nreturn -width <= offset < width",
         "width > 0", "ret == And(offset >= -width, offset < width)",
         (((0, 0), None), ((-3, 3), True), ((-4, 3), False), ((3, 3), False)),
         "bool"),
    Case("wrap_shift", "slot delta size",
         "Reject nonpositive size and any initial slot outside zero through size minus one. "
         "Move by the signed delta, wrapping around the ring in either direction.",
         "if size <= 0 or not 0 <= slot < size:\n    raise ValueError()\n"
         "return (slot + delta) % size",
         "And(size > 0, slot >= 0, slot < size)", "ret == (slot + delta) % size",
         (((0, 0, 0), None), ((3, 0, 3), None), ((0, -1, 3), 2), ((2, 2, 3), 1))),
    Case("signed_remainder", "amount scale",
         "Reject a zero scale. Return the remainder from dividing by scale after "
         "rounding the quotient toward negative infinity. Negative scales are allowed.",
         "if not scale:\n    raise ValueError()\nreturn amount % scale",
         "scale != 0",
         "ret == amount - scale * If(scale > 0, amount / scale, (-amount) / (-scale))",
         (((1, 0), None), ((7, -3), -2), ((-7, 3), 2), ((-7, -3), -1), ((6, -3), 0))),
    Case("between_exclusive", "a b c",
         "Return whether b is strictly between a and c. The endpoints can "
         "be supplied in either order. All integers are valid inputs.",
         "return (a < b < c) or (c < b < a)",
         "True", "ret == Or(And(a < b, b < c), And(c < b, b < a))",
         (((-1, 0, 1), True), ((1, 0, -1), True), ((0, 0, 1), False),
          ((2, 1, 3), False)), "bool"),
)
