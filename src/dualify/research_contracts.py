"""Typed scalar formula subset for post-freeze experiments with model output."""

import ast
import operator
from collections.abc import Iterable
from typing import Any

import z3


class FormulaError(ValueError):
    """A formula is outside the experimental subset."""


_BINARY = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.truediv,
    ast.Mod: operator.mod,
}
_COMPARE = {
    ast.Eq: operator.eq,
    ast.NotEq: operator.ne,
    ast.Lt: operator.lt,
    ast.LtE: operator.le,
    ast.Gt: operator.gt,
    ast.GtE: operator.ge,
}


def _extreme(*values: Any, maximum: bool) -> Any:
    if not values:
        raise FormulaError("min/max requires an operand")
    result = values[0]
    for value in values[1:]:
        keep = result >= value if maximum else result <= value
        result = z3.If(keep, result, value)
    return result


_CALLS = {
    "And": z3.And,
    "Or": z3.Or,
    "Not": z3.Not,
    "Implies": z3.Implies,
    "If": z3.If,
    "Abs": z3.Abs,
    "abs": z3.Abs,
    "min": lambda *values: _extreme(*values, maximum=False),
    "max": lambda *values: _extreme(*values, maximum=True),
    "floor": lambda value: value if z3.is_int(value) else z3.ToInt(value),
}


def _arithmetic(value: Any) -> Any:
    if not z3.is_arith(value):
        raise FormulaError("expected a number")
    return value


def _bool(value: Any) -> z3.BoolRef:
    if not z3.is_bool(value):
        raise FormulaError("expected a boolean expression")
    return value


def _term(node: ast.expr, names: dict[str, Any]) -> Any:
    def child(expr: ast.expr) -> Any:
        return _term(expr, names)

    match node:
        case ast.Constant(value=value) if type(value) is bool:
            return z3.BoolVal(value)
        case ast.Constant(value=value) if type(value) is int:
            return z3.IntVal(value)
        case ast.Name(id=name) if name in names:
            return names[name]
        case ast.BinOp(left=left, op=op, right=right) if type(op) in _BINARY:
            return _BINARY[type(op)](_arithmetic(child(left)), _arithmetic(child(right)))
        case ast.UnaryOp(op=ast.USub(), operand=operand):
            return -_arithmetic(child(operand))
        case ast.UnaryOp(op=ast.UAdd(), operand=operand):
            return _arithmetic(child(operand))
        case ast.UnaryOp(op=ast.Not(), operand=operand):
            return z3.Not(_bool(child(operand)))
        case ast.BoolOp(op=op, values=operands):
            combine = z3.And if isinstance(op, ast.And) else z3.Or
            return combine(*[_bool(child(value)) for value in operands])
        case ast.Compare(left=left, ops=ops, comparators=rest):
            terms = [child(left), *map(child, rest)]
            comparisons = []
            for index, comparison in enumerate(ops):
                a, b = terms[index:index + 2]
                if a.sort() != b.sort() or type(comparison) not in _COMPARE:
                    raise FormulaError("incompatible comparison")
                comparisons.append(_bool(_COMPARE[type(comparison)](a, b)))
            return z3.And(*comparisons)
        case ast.Call(func=ast.Name(id=name), args=args, keywords=[]) if name in _CALLS:
            return _apply(name, list(map(child, args)))
        case _:
            raise FormulaError(f"unsupported formula node: {type(node).__name__}")


def _apply(name: str, args: list[Any]) -> Any:
    arity = {"Not": 1, "Implies": 2, "Abs": 1, "abs": 1, "floor": 1}.get(name)
    if arity is not None and len(args) != arity:
        raise FormulaError(f"{name} requires {arity} operands")
    if name in {"And", "Or", "Not", "Implies"}:
        args = list(map(_bool, args))
    elif name == "If":
        if len(args) != 3 or args[1].sort() != args[2].sort():
            raise FormulaError("If requires a condition and two values of the same type")
        _bool(args[0])
    else:
        args = list(map(_arithmetic, args))
    return _CALLS[name](*args)


def _formula(text: str, names: dict[str, Any]) -> z3.BoolRef:
    if not isinstance(text, str) or len(text) > 4000:
        raise FormulaError("expected a short formula string")
    try:
        return _bool(_term(ast.parse(text.strip(), mode="eval").body, names))
    except (SyntaxError, z3.Z3Exception, TypeError, RecursionError) as exc:
        raise FormulaError(str(exc)) from exc


class Contract:
    """Parse a contract over integer inputs and an integer or boolean return value."""

    def __init__(
        self, args: dict[str, str], return_type: str, pre: list[str], post: str,
    ) -> None:
        if "ret" in args or set(args.values()) - {"int"} or return_type not in {"int", "bool"}:
            raise FormulaError("unsupported signature")
        if not isinstance(pre, list) or not all(isinstance(item, str) for item in pre):
            raise FormulaError("expected domain_constraints to be a list of strings")
        self.vars = {name: z3.Int(name) for name in args}
        self.ret = z3.Int("ret") if return_type == "int" else z3.Bool("ret")
        self.pre = z3.And(*[_formula(item, self.vars) for item in pre])
        self.post = _formula(post, {**self.vars, "ret": self.ret})

    def at(self, expr: z3.BoolRef, args: tuple[int, ...]) -> z3.BoolRef:
        terms = [
            (symbol, z3.IntVal(value))
            for symbol, value in zip(self.vars.values(), args, strict=True)
        ]
        return z3.simplify(z3.substitute(expr, *terms))

    def value(self, value: int | bool) -> Any:
        if z3.is_bool(self.ret):
            if type(value) is not bool:
                raise FormulaError("expected a boolean return")
            return z3.BoolVal(value)
        if type(value) is not int:
            raise FormulaError("expected an integer return")
        return z3.IntVal(value)


def query(*terms: z3.BoolRef, timeout_ms: int = 2000) -> z3.Solver:
    solver = z3.Solver()
    solver.set(timeout=timeout_ms)
    solver.add(*terms)
    return solver


def relation(generated: Contract, expected: Contract) -> tuple[str, str]:
    """Return SMT status for domain XOR and post XOR under the expected domain."""
    pre_xor = query(z3.Xor(generated.pre, expected.pre))
    post_xor = query(expected.pre, z3.Xor(generated.post, expected.post))
    return str(pre_xor.check()), str(post_xor.check())


def counterexample(
    contract: Contract, inputs: tuple[int, ...], expected: int | bool | None,
) -> dict[str, object] | None:
    input_map = dict(zip(contract.vars, inputs, strict=True))
    pre = contract.at(contract.pre, inputs)
    if z3.is_false(pre) and expected is not None:
        return {"args": input_map, "kind": "rejects_input", "ret": None}
    if not z3.is_true(pre):
        return None
    if expected is None:
        return {"args": input_map, "kind": "accepts_input", "ret": None}

    actual = contract.value(expected)
    post = contract.at(contract.post, inputs)
    if z3.is_false(z3.simplify(z3.substitute(post, (contract.ret, actual)))):
        return {"args": input_map, "kind": "rejects_return", "ret": expected}
    solver = query(post, contract.ret != actual, timeout_ms=100)
    if solver.check() == z3.sat:
        alternative = solver.model().eval(contract.ret, model_completion=True)
        grounded = z3.simplify(z3.substitute(post, (contract.ret, alternative)))
        if z3.is_true(grounded):
            value = z3.is_true(alternative) if z3.is_bool(alternative) else alternative.as_long()
            return {"args": input_map, "kind": "admits_wrong_return", "ret": value}
    return None


def find_witness(
    contract: Contract, examples: Iterable[tuple[tuple[int, ...], int | bool | None]],
) -> dict[str, object] | None:
    for inputs, expected in examples:
        witness = counterexample(contract, inputs, expected)
        if witness:
            return witness
    return None
