"""Translate an isolated, loop-free scalar Python function to a return contract."""

import ast
from dataclasses import dataclass
from typing import Literal, TypedDict


class UnsupportedSource(ValueError):
    """The function is outside the compiler's supported Python fragment."""


class ContractPayload(TypedDict):
    domain_constraints: list[str]
    postcondition: str


Sort = Literal["int", "bool"]
_COMPARISONS = {
    ast.Eq: "==", ast.NotEq: "!=", ast.Lt: "<", ast.LtE: "<=", ast.Gt: ">", ast.GtE: ">=",
}
_ARITHMETIC = {ast.Add: "+", ast.Sub: "-", ast.Mult: "*"}
_BUILTINS = {"abs", "min", "max"}
_EXCEPTIONS = {"ValueError", "TypeError", "ZeroDivisionError", "IndexError"}


@dataclass(frozen=True)
class _Term:
    value: str
    sort: Sort
    defined: str = "True"


@dataclass(frozen=True)
class _Flow:
    defined: str
    value: str
    falls_through: bool = False


def _not(test: str) -> str:
    if test == "True":
        return "False"
    if test == "False":
        return "True"
    return f"Not({test})"


def _and(*tests: str) -> str:
    if "False" in tests:
        return "False"
    conditions = [test for test in tests if test != "True"]
    if not conditions:
        return "True"
    if len(conditions) == 1:
        return conditions[0]
    return f"And({', '.join(conditions)})"


def _if(test: str, yes: str, no: str) -> str:
    if yes == no or test == "True":
        return yes
    if test == "False":
        return no
    if yes == "True" and no == "False":
        return test
    if yes == "False" and no == "True":
        return _not(test)
    return f"If({test}, {yes}, {no})"


def _truth(term: _Term) -> str:
    return term.value if term.sort == "bool" else f"({term.value} != 0)"


def _choose(test: _Term, yes: _Term, no: _Term) -> _Term:
    if yes.sort != no.sort:
        raise UnsupportedSource("conditional values have different types")
    truth = _truth(test)
    return _Term(
        _if(truth, yes.value, no.value), yes.sort,
        _and(test.defined, _if(truth, yes.defined, no.defined)),
    )


def _short_circuit(items: list[_Term], *, conjunction: bool) -> _Term:
    result = items[-1]
    for item in reversed(items[:-1]):
        first_value = _Term(str(not conjunction) if item.sort == "bool" else item.value,
                            item.sort)
        if conjunction:
            result = _choose(item, result, first_value)
        else:
            result = _choose(item, first_value, result)
    return result


class _Compiler:
    def __init__(self, names: set[str], returns: Sort, python_division: bool) -> None:
        self.names = names
        self.returns = returns
        self.python_division = python_division
        self.default = "0" if returns == "int" else "False"

    def suite(self, statements: list[ast.stmt], tail: _Flow) -> _Flow:
        for statement in reversed(statements):
            match statement:
                case ast.Return(value=ast.expr() as value):
                    result = self.term(value)
                    if result.sort != self.returns:
                        raise UnsupportedSource("return does not match annotation")
                    tail = _Flow(result.defined, result.value)
                case ast.Raise(exc=exception, cause=None) if _safe_raise(exception):
                    tail = _Flow("False", self.default)
                case ast.If(test=condition, body=yes, orelse=no):
                    test = self.term(condition)
                    truth = _truth(test)
                    consequent = self.suite(yes, tail)
                    alternative = self.suite(no, tail)
                    tail = _Flow(
                        _and(test.defined, _if(truth, consequent.defined, alternative.defined)),
                        _if(truth, consequent.value, alternative.value),
                        consequent.falls_through or alternative.falls_through,
                    )
                case _:
                    raise UnsupportedSource(f"unsupported statement: {type(statement).__name__}")
        return tail

    def term(self, node: ast.expr) -> _Term:
        match node:
            case ast.Constant(value=value) if type(value) is bool:
                return _Term(str(value), "bool")
            case ast.Constant(value=value) if type(value) is int:
                return _Term(str(value), "int")
            case ast.Name(id=name) if name in self.names:
                return _Term(name, "int")
            case ast.UnaryOp(op=ast.USub() | ast.UAdd() as op, operand=value):
                item = self.term(value)
                self.require_int(item)
                sign = "-" if isinstance(op, ast.USub) else "+"
                return _Term(f"({sign}{item.value})", "int", item.defined)
            case ast.UnaryOp(op=ast.Not(), operand=value):
                item = self.term(value)
                return _Term(_not(_truth(item)), "bool", item.defined)
            case ast.BinOp(left=left, op=op, right=right) if type(op) in _ARITHMETIC:
                a, b = self.term(left), self.term(right)
                self.require_int(a, b)
                value = f"({a.value} {_ARITHMETIC[type(op)]} {b.value})"
                return _Term(value, "int", _and(a.defined, b.defined))
            case ast.BinOp(left=left, op=ast.FloorDiv() | ast.Mod() as op, right=right):
                a, b = self.term(left), self.term(right)
                self.require_int(a, b)
                remainder = isinstance(op, ast.Mod)
                operator = "%" if remainder else "/"
                value = f"({a.value} {operator} {b.value})"
                if self.python_division:
                    # SMT integer division floors with a positive divisor.
                    negative = f"((-{a.value}) {operator} (-{b.value}))"
                    if remainder:
                        negative = f"(-{negative})"
                    value = _if(f"({b.value} > 0)", value, negative)
                return _Term(value, "int", _and(a.defined, b.defined, f"({b.value} != 0)"))
            case ast.Compare(left=left, ops=ops, comparators=right):
                a = self.term(left)
                comparisons = []
                for comparison, child in zip(ops, right, strict=True):
                    b = self.term(child)
                    if type(comparison) not in _COMPARISONS or a.sort != b.sort or (
                        a.sort == "bool" and not isinstance(comparison, (ast.Eq, ast.NotEq))
                    ):
                        raise UnsupportedSource("unsupported comparison")
                    value = f"({a.value} {_COMPARISONS[type(comparison)]} {b.value})"
                    comparisons.append(_Term(value, "bool", _and(a.defined, b.defined)))
                    a = _Term(b.value, b.sort)
                return _short_circuit(comparisons, conjunction=True)
            case ast.BoolOp(op=op, values=values):
                return _short_circuit(list(map(self.term, values)),
                                      conjunction=isinstance(op, ast.And))
            case ast.IfExp(test=test, body=yes, orelse=no):
                return _choose(self.term(test), self.term(yes), self.term(no))
            case ast.Call(func=ast.Name(id=name), args=args, keywords=[]) if name in _BUILTINS:
                if not (len(args) == 1 if name == "abs" else len(args) >= 2):
                    raise UnsupportedSource(f"unsupported arity for {name}")
                items = list(map(self.term, args))
                self.require_int(*items)
                value = f"{name}({', '.join(item.value for item in items)})"
                return _Term(value, "int", _and(*(item.defined for item in items)))
            case _:
                raise UnsupportedSource(f"unsupported expression: {type(node).__name__}")

    @staticmethod
    def require_int(*items: _Term) -> None:
        if any(item.sort != "int" for item in items):
            raise UnsupportedSource("expected integer operands")


def _safe_raise(exception: ast.expr | None) -> bool:
    match exception:
        case ast.Name(id=name):
            return name in _EXCEPTIONS
        case ast.Call(func=ast.Name(id=name), args=args, keywords=[]):
            return name in _EXCEPTIONS and (
                not args or len(args) == 1
                and isinstance(args[0], ast.Constant) and type(args[0].value) is str
            )
        case _:
            return False


def compile_contract(source: str, *, python_division: bool = True) -> ContractPayload:
    """Compile the domain of normal returns and their result for plain builtin integers."""
    try:
        tree = ast.parse(source)
        compile(tree, "<contract source>", "exec")
    except (SyntaxError, ValueError, RecursionError) as exc:
        raise UnsupportedSource(str(exc)) from exc

    match tree.body:
        case [ast.FunctionDef(name=name, args=args, body=body, decorator_list=[],
                              returns=ast.Name(id="int" | "bool" as return_type)) as function]:
            pass
        case _:
            raise UnsupportedSource("expected one annotated function definition")
    if (
        name in _BUILTINS | _EXCEPTIONS or getattr(function, "type_params", False)
        or args.posonlyargs or args.vararg or args.kwarg or args.defaults or args.kwonlyargs
        or any(not isinstance(arg.annotation, ast.Name) or arg.annotation.id != "int"
               or arg.arg in _BUILTINS | _EXCEPTIONS | {"ret"} for arg in args.args)
    ):
        raise UnsupportedSource("unsupported signature")

    compiler = _Compiler({arg.arg for arg in args.args}, return_type, python_division)
    if ast.get_docstring(function, clean=False) is not None:
        body = body[1:]
    try:
        flow = compiler.suite(body, _Flow("False", compiler.default, falls_through=True))
    except RecursionError as exc:
        raise UnsupportedSource("function is too deeply nested") from exc
    if flow.falls_through:
        raise UnsupportedSource("function can fall through without an explicit result")
    post = f"ret == {flow.value}"
    if max(len(flow.defined), len(post)) > 4000:
        raise UnsupportedSource("compiled formula exceeds the evaluator's length limit")
    return {
        "domain_constraints": [] if flow.defined == "True" else [flow.defined],
        "postcondition": post,
    }
