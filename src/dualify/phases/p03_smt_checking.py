import ast
import re
from dataclasses import dataclass
from typing import Any, Literal

import z3

from dualify.formula_parser import extract_quantifier_binders, normalize_formula
from dualify.types import ExtractionResult, SmtResult


@dataclass
class CaseSpec:
    benchmark_id: str
    arg_types: dict[str, str]
    return_type: str


def _sanitize_sort_name(type_name: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_]", "_", type_name).strip("_")
    return cleaned or "Unknown"


def _normalize_type_name(type_name: str) -> str:
    return "".join(type_name.split())


def _element_sort_for_generic(type_name: str) -> z3.SortRef:
    lowered = _normalize_type_name(type_name).lower()
    if lowered in {"t", "u", "any", "direction", "activity"}:
        return z3.IntSort()
    return _sort_for_type(type_name)


def _sequence_element_sort(inner_type: str) -> z3.SortRef:
    inner = _normalize_type_name(inner_type).lower()
    tuple_match = re.fullmatch(r"tuple\[(.+)\]", inner)
    if tuple_match:
        parts = [
            part.strip()
            for part in tuple_match.group(1).replace("...", "").split(",")
            if part.strip()
        ]
        elem_type = parts[0] if parts else "int"
        return z3.SeqSort(_element_sort_for_generic(elem_type))
    if inner.startswith("list["):
        return z3.SeqSort(z3.SeqSort(z3.IntSort()))
    return _element_sort_for_generic(inner_type)


def _sort_for_type(type_name: str) -> z3.SortRef:
    normalized = _normalize_type_name(type_name)
    lowered = normalized.lower()

    if lowered in {"int", "integer"}:
        return z3.IntSort()
    if lowered == "bool":
        return z3.BoolSort()
    if lowered in {"float", "real"}:
        return z3.RealSort()
    if lowered == "str":
        return z3.StringSort()
    if "ndarray" in lowered:
        return z3.SeqSort(z3.RealSort())

    optional_match = re.fullmatch(r"optional\[(.+)\]", lowered)
    if optional_match:
        return _sort_for_type(optional_match.group(1))

    container_match = re.fullmatch(r"(list|tuple|set|iterable|mutablemapping)\[(.+)\]", lowered)
    if container_match:
        kind, inner = container_match.group(1), container_match.group(2).strip()
        if kind == "tuple":
            if "..." in inner:
                return z3.SeqSort(z3.IntSort())
            parts = [part.strip() for part in inner.replace("...", "").split(",") if part.strip()]
            elem_type = parts[0] if parts else "int"
            return z3.SeqSort(_element_sort_for_generic(elem_type))
        return z3.SeqSort(_sequence_element_sort(inner))

    if re.match(r"^[A-Z]", type_name):
        return z3.SeqSort(z3.IntSort())

    return z3.DeclareSort(f"T_{_sanitize_sort_name(type_name)}")


def _make_var(name: str, type_name: str) -> Any:
    return z3.Const(name, _sort_for_type(type_name))


class _BoolOpTransformer(ast.NodeTransformer):
    def visit_BoolOp(self, node: ast.BoolOp) -> ast.AST:
        self.generic_visit(node)
        func_name = "And" if isinstance(node.op, ast.And) else "Or"
        return ast.Call(func=ast.Name(id=func_name, ctx=ast.Load()), args=node.values, keywords=[])

    def visit_UnaryOp(self, node: ast.UnaryOp) -> ast.AST:
        self.generic_visit(node)
        if isinstance(node.op, ast.Not):
            return ast.Call(
                func=ast.Name(id="Not", ctx=ast.Load()),
                args=[node.operand],
                keywords=[],
            )
        return node

    def visit_BinOp(self, node: ast.BinOp) -> ast.AST:
        self.generic_visit(node)
        if isinstance(node.op, ast.RShift):
            return ast.Call(
                func=ast.Name(id="Implies", ctx=ast.Load()),
                args=[node.left, node.right],
                keywords=[],
            )
        return node


def _rewrite_expression(expr: str, benchmark_id: str) -> str:
    rewritten = expr
    if re.fullmatch(
        r"\s*[A-Za-z_][A-Za-z0-9_]*\s+is\s+an?\s+(?:integer|int)\s*",
        rewritten,
    ):
        return "True"

    # An empty benchmark ID is used by extraction_parseable().  Do not run
    # the function-call replacement in that case: the regex would otherwise
    # match any call's parentheses and corrupt valid expressions such as If(...).
    if benchmark_id:
        rewritten = re.sub(
            rf"\b{re.escape(benchmark_id)}\s*\([^)]*\)",
            "ret",
            rewritten,
        )
    rewritten = re.sub(r"\bEven\s*\(\s*([^()]+)\s*\)", r"((\1) % 2 == 0)", rewritten)
    rewritten = rewritten.replace("/\\", " and ")
    rewritten = rewritten.replace("\\/", " or ")
    rewritten = rewritten.replace("==>", " >> ")
    rewritten = rewritten.replace("=>", " >> ")
    rewritten = rewritten.replace("<->", " == ")
    rewritten = rewritten.replace("&&", " and ")
    rewritten = rewritten.replace("||", " or ")
    rewritten = rewritten.replace("->", " >> ")
    rewritten = rewritten.replace(";", " and ")
    rewritten = rewritten.replace("//", "/")
    rewritten = re.sub(r"\blen\s*\(", "Length(", rewritten)
    rewritten = re.sub(
        r"\b([A-Za-z_][A-Za-z0-9_]*)\.([A-Za-z_][A-Za-z0-9_]*)\b",
        r"\1_\2",
        rewritten,
    )
    rewritten = re.sub(r"\bAnd\b(?!\()", " and ", rewritten)
    rewritten = re.sub(r"\bOr\b(?!\()", " or ", rewritten)
    rewritten = re.sub(r"\bNot\b(?!\()", " not ", rewritten)
    rewritten = re.sub(r"\bImplies\b(?!\()", " >> ", rewritten)
    return rewritten


def _canonicalize_expression(expr: str, benchmark_id: str) -> str:
    normalized = normalize_formula(expr)
    rewritten = _rewrite_expression(normalized, benchmark_id)
    try:
        parsed = ast.parse(rewritten, mode="eval")
        transformed = _BoolOpTransformer().visit(parsed)
        ast.fix_missing_locations(transformed)
        return ast.unparse(transformed)
    except Exception:
        return rewritten


def _safe_eval(expr: str, scope: dict[str, Any], benchmark_id: str) -> Any:
    normalized_expr = _canonicalize_expression(expr, benchmark_id)
    sqrt_fn = z3.Function("sqrt", z3.RealSort(), z3.RealSort())

    def _max(*values: Any) -> Any:
        if not values:
            raise ValueError("max requires at least one argument")
        result = values[0]
        for value in values[1:]:
            result = z3.If(value >= result, value, result)
        return result

    def _min(*values: Any) -> Any:
        if not values:
            raise ValueError("min requires at least one argument")
        result = values[0]
        for value in values[1:]:
            result = z3.If(value <= result, value, result)
        return result

    def _floor(value: Any) -> Any:
        if hasattr(value, "sort") and value.sort().kind() == z3.Z3_INT_SORT:
            value = z3.ToReal(value)
        return z3.ToInt(value)

    def _is_string_sort(sort: Any) -> bool:
        return str(sort) == "String"

    def _contains(seq: Any, elem: Any) -> Any:
        if hasattr(seq, "sort"):
            if _is_string_sort(seq.sort()):
                if isinstance(elem, str):
                    return z3.Contains(seq, elem)
                return z3.Contains(seq, elem)
            if (
                hasattr(elem, "sort")
                and elem.sort().kind() == z3.Z3_INT_SORT
                and seq.sort().kind() == z3.Z3_SEQ_SORT
            ):
                try:
                    return z3.Contains(seq, _unit(elem))
                except z3.Z3Exception:
                    return z3.And(elem >= 0, elem < z3.Length(seq))
        if isinstance(elem, str):
            return z3.Contains(seq, elem)
        if hasattr(elem, "sort"):
            if elem.sort().kind() == z3.Z3_SEQ_SORT:
                return z3.Contains(seq, elem)
            return z3.Contains(seq, _unit(elem))
        return z3.Contains(seq, _unit(elem))

    def _unit(value: Any) -> Any:
        """Make a Z3 sequence unit, also accepting Python literal values.

        z3.Unit(1) raises AttributeError (int has no ctx_ref). Formula
        expressions often contain Unit(1) / Unit(3), so coerce Python
        literals to Z3 expressions before calling z3.Unit.
        """
        if isinstance(value, bool):
            value = z3.BoolVal(value)
        elif isinstance(value, int):
            value = z3.IntVal(value)
        elif isinstance(value, float):
            value = z3.RealVal(str(value))
        elif isinstance(value, str):
            value = z3.StringVal(value)
        return z3.Unit(value)

    def _string_lit(value: Any) -> Any:
        if isinstance(value, str):
            return z3.StringVal(value)
        return value

    def _char_lit(value: Any) -> Any:
        if isinstance(value, str):
            return z3.CharVal(value)
        return value

    def _sqrt(value: Any) -> Any:
        if hasattr(z3, "Sqrt"):
            return z3.Sqrt(value)
        return sqrt_fn(value)

    def _pow(lhs: Any, rhs: Any, modulus: Any = None) -> Any:
        # Support 3-arg modular exponentiation (Python's pow(a, b, m)). Z3 has no
        # native modexp, so model it as (a ** b) % m; with a symbolic exponent
        # this is nonlinear and Z3 will answer unknown rather than crash.
        result = lhs**rhs
        if modulus is not None:
            return result % modulus
        return result

    def _is_digit_string(value: Any) -> Any:
        if hasattr(z3, "InRe"):
            return z3.InRe(value, z3.Star(z3.Range("0", "9")))
        return z3.BoolVal(True)

    z3_callables = {
        name: getattr(z3, name)
        for name in dir(z3)
        if not name.startswith("_") and callable(getattr(z3, name, None))
    }
    custom_callables = {
        "And": z3.And,
        "Or": z3.Or,
        "Not": z3.Not,
        "Implies": z3.Implies,
        "If": z3.If,
        "Abs": z3.Abs,
        "Length": z3.Length,
        "Contains": _contains,
        "String": _string_lit,
        "Char": _char_lit,
        "PrefixOf": z3.PrefixOf,
        "SuffixOf": z3.SuffixOf,
        "Concat": z3.Concat,
        "Unit": _unit,
        "floor": _floor,
        "max": _max,
        "min": _min,
        "sqrt": _sqrt,
        "pow": _pow,
        "IsDigitString": _is_digit_string,
        "True": True,
        "False": False,
    }
    env = {}
    env.update(z3_callables)
    env.update(custom_callables)
    env.update(scope)
    # Quantifier binders are locally bound variables in formulas. If the model
    # emits ForAll([i], ...) / Exists(i, ...), ensure those names exist in eval env.
    for binder in extract_quantifier_binders(normalized_expr):
        env.setdefault(binder, z3.Int(binder))
    return eval(normalized_expr, {"__builtins__": {}}, env)


def _has_forbidden_python_bool_ops(expr: str) -> bool:
    return bool(re.search(r"(^|\s)(and|or|not)(\s|$)", expr))


def _has_bool_arithmetic_hint(expr: str) -> bool:
    # Conservative guard: blocks frequent invalid patterns like a*(x > 0).
    has_arith_before_group = any(
        token in expr for token in ("*(", "* (", "+(", "+ (", "-(", "- (", "/(", "/ (")
    )
    has_comparator = any(token in expr for token in ("==", "!=", "<=", ">=", "<", ">"))
    return has_arith_before_group and has_comparator


def _mod_denominators(expr: str) -> list[str]:
    # Capture simple denominator symbols in `lhs % den`.
    return re.findall(r"%\s*([A-Za-z_][A-Za-z0-9_]*)", expr)


def _has_guard_for_denominator(den: str, all_expr_text: str) -> bool:
    guard_patterns = [
        f"{den} != 0",
        f"Not({den} == 0)",
        f"Not({den}==0)",
        f"If({den} == 0",
        f"If({den}==0",
    ]
    return any(pattern in all_expr_text for pattern in guard_patterns)


def _validate_formula_safety(extraction: ExtractionResult) -> list[str]:
    issues: list[str] = []
    expressions = [*extraction.domain_constraints, extraction.postcondition]
    all_expr_text = " ".join(expressions)

    for expr in expressions:
        if _has_forbidden_python_bool_ops(expr):
            issues.append("forbidden_python_bool_ops")
            break
        if _has_bool_arithmetic_hint(expr):
            issues.append("bool_arithmetic_mix")
            break

    denominators: set[str] = set()
    for expr in expressions:
        denominators.update(_mod_denominators(expr))
    for den in sorted(denominators):
        if not _has_guard_for_denominator(den, all_expr_text):
            issues.append(f"unguarded_mod_denominator:{den}")

    return issues


def _strip_exhaustive_zero_split_constraints(constraints: list[str]) -> list[str]:
    pattern = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*(>=|>|<=|<)\s*0\s*$")
    index_by_key: dict[tuple[str, str], set[int]] = {}
    for i, expr in enumerate(constraints):
        match = pattern.fullmatch(expr)
        if not match:
            continue
        var_name, op = match.group(1), match.group(2)
        index_by_key.setdefault((var_name, op), set()).add(i)

    complementary_pairs = [(">=", "<"), (">", "<="), ("<=", ">"), ("<", ">=")]
    drop_indexes: set[int] = set()
    variables = {var for (var, _op) in index_by_key}
    for var in variables:
        for lhs, rhs in complementary_pairs:
            lhs_indexes = index_by_key.get((var, lhs), set())
            rhs_indexes = index_by_key.get((var, rhs), set())
            if lhs_indexes and rhs_indexes:
                drop_indexes.update(lhs_indexes)
                drop_indexes.update(rhs_indexes)

    return [expr for idx, expr in enumerate(constraints) if idx not in drop_indexes]


_TOKEN_PATTERN = re.compile(r"\b[A-Za-z_][A-Za-z0-9_]*\b")
_RESERVED_FORMULA_TOKENS = {
    "True",
    "False",
}


def _infer_symbol_type(name: str, expressions: list[str]) -> str:
    if name.startswith("self_"):
        return "int"
    joined = " ".join(expressions)
    if re.search(rf"\b{re.escape(name)}\s*\[", joined):
        return "List[int]"
    if re.search(rf"\bContains\s*\(\s*{re.escape(name)}\b", joined):
        return "str"
    if re.search(rf"\bLength\s*\(\s*{re.escape(name)}\b", joined):
        if re.search(rf"\b{re.escape(name)}\s*\[", joined):
            return "List[int]"
        return "str"
    if re.search(rf"\b{re.escape(name)}\s*[%+\-*/<>]", joined) or re.search(
        rf"[%+\-*/<>]\s*{re.escape(name)}\b",
        joined,
    ):
        return "int"
    return "str"


def _free_identifiers(expr: str) -> set[str]:
    """Return the set of identifiers that appear in expr but are not used as a call target.

    Used by the well-formedness check; intentionally lenient on parse failures
    (returns an empty set rather than raising), because the surrounding code
    already handles parse errors via _safe_eval.
    """
    if not expr.strip():
        return set()
    called_names: set[str] = set()
    try:
        tree = ast.parse(expr, mode="eval")
        called_names = {
            node.func.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }
    except Exception:
        return set()
    return {
        token
        for token in _TOKEN_PATTERN.findall(expr)
        if token not in _RESERVED_FORMULA_TOKENS
        and token not in called_names
        and not token.isdigit()
    }


def _check_post_well_formedness(spec_post: str, code_post: str) -> str:
    """Detect post-conditions whose comparison would be vacuous.

    Returns "ok" when the equivalence check is meaningful, or a specific
    reason string otherwise. The reasons are:

      - "neither_post_mentions_ret": the postconditions do not constrain
        the return value at all (e.g. both are pure input predicates).
      - "post_ret_asymmetry": one side mentions ret and the other does
        not, so the equivalence check ranges over disjoint variable sets
        and any verdict is semantically vacuous.
      - "disjoint_post_vocab": both sides mention ret, but the rest of
        their vocabularies do not overlap at all, which usually means
        the two extractions are talking about different aspects of the
        function.

    The third check is intentionally weak: many genuine equivalences
    legitimately involve only `ret` (e.g. `ret == 5` vs `ret == 5`), so
    we only flag the disjoint-vocab case when both formulas reference
    additional symbols and those symbol sets do not intersect.
    """
    spec_vars = _free_identifiers(spec_post)
    code_vars = _free_identifiers(code_post)
    spec_has_ret = "ret" in spec_vars
    code_has_ret = "ret" in code_vars
    if not (spec_has_ret or code_has_ret):
        return "neither_post_mentions_ret"
    if spec_has_ret != code_has_ret:
        return "post_ret_asymmetry"
    spec_extra = spec_vars - {"ret"}
    code_extra = code_vars - {"ret"}
    if spec_extra and code_extra and not (spec_extra & code_extra):
        return "disjoint_post_vocab"
    return "ok"


_SOLVER_TIMEOUT_MS = 5_000


def _check_with_status(solver: z3.Solver) -> z3.CheckSatResult:
    """Run solver.check() and return its raw status, never coerced to sat/unsat.

    Centralized so the call site can distinguish unknown from unsat.
    """
    solver.set("timeout", _SOLVER_TIMEOUT_MS)
    return solver.check()


def _unknown_reason(solver: z3.Solver, status: z3.CheckSatResult) -> str | None:
    """Record whether unknown means timeout, incomplete theory, etc."""
    return str(solver.reason_unknown()) if status == z3.unknown else None


def _augment_scope_from_formulas(
    scope: dict[str, Any],
    known_names: set[str],
    expressions: list[str],
) -> None:
    found_names: set[str] = set()
    binder_names: set[str] = set()
    for expr in expressions:
        binder_names |= extract_quantifier_binders(expr)
    for expr in expressions:
        called_names: set[str] = set()
        try:
            tree = ast.parse(expr, mode="eval")
            called_names = {
                node.func.id
                for node in ast.walk(tree)
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
            }
        except Exception:
            called_names = set()
        for token in _TOKEN_PATTERN.findall(expr):
            if token in _RESERVED_FORMULA_TOKENS:
                continue
            if token in called_names:
                continue
            if token in binder_names:
                continue
            if token.isdigit():
                continue
            found_names.add(token)
    for name in sorted(found_names):
        if name in known_names:
            continue
        inferred_type = _infer_symbol_type(name, expressions)
        scope[name] = _make_var(name, inferred_type)
        known_names.add(name)


def check_equivalence(
    case_spec: CaseSpec,
    spec_logic: ExtractionResult,
    code_logic: ExtractionResult,
) -> SmtResult:
    scope: dict[str, Any] = {}
    known_names: set[str] = set()
    for arg_name, type_name in case_spec.arg_types.items():
        scope[arg_name] = _make_var(arg_name, type_name)
        known_names.add(arg_name)
    scope["ret"] = _make_var("ret", case_spec.return_type)
    known_names.add("ret")

    try:
        clean_spec_constraints = _strip_exhaustive_zero_split_constraints(
            [
                _canonicalize_expression(c, case_spec.benchmark_id)
                for c in spec_logic.domain_constraints
            ]
        )
        clean_code_constraints = _strip_exhaustive_zero_split_constraints(
            [
                _canonicalize_expression(c, case_spec.benchmark_id)
                for c in code_logic.domain_constraints
            ]
        )
        _augment_scope_from_formulas(
            scope,
            known_names,
            [
                *clean_spec_constraints,
                *clean_code_constraints,
                _canonicalize_expression(spec_logic.postcondition, case_spec.benchmark_id),
                _canonicalize_expression(code_logic.postcondition, case_spec.benchmark_id),
            ],
        )
        spec_constraints = [
            _safe_eval(c, scope, case_spec.benchmark_id) for c in clean_spec_constraints
        ]
        code_constraints = [
            _safe_eval(c, scope, case_spec.benchmark_id) for c in clean_code_constraints
        ]
        spec_post = _safe_eval(
            _canonicalize_expression(spec_logic.postcondition, case_spec.benchmark_id),
            scope,
            case_spec.benchmark_id,
        )
        code_post = _safe_eval(
            _canonicalize_expression(code_logic.postcondition, case_spec.benchmark_id),
            scope,
            case_spec.benchmark_id,
        )
    except Exception as exc:
        return SmtResult(
            benchmark_id=case_spec.benchmark_id,
            equivalent=False,
            reason=f"formula_parse_error: {exc}",
            counterexample=None,
        )

    # Compute well-formedness from the raw post strings so the check sees the
    # author-visible vocabulary (e.g. `self_code`, `ret`). The result gates
    # any later claim of equivalence: if it is not "ok", the equivalence
    # verdict is vacuous and must be flagged rather than reported as PASS.
    post_well_formedness = _check_post_well_formedness(
        spec_logic.postcondition, code_logic.postcondition
    )

    spec_assumptions = z3.And(*spec_constraints) if spec_constraints else z3.BoolVal(True)
    code_assumptions = z3.And(*code_constraints) if code_constraints else z3.BoolVal(True)

    def _numeric_from_model_value(value: z3.ExprRef) -> int | float:
        if z3.is_int_value(value):
            return value.as_long()
        if z3.is_rational_value(value):
            return float(value.as_fraction())
        # Fallback for numerals that are not plain int/rational.
        return float(value.as_decimal(20).replace("?", ""))

    def _model_value_to_python(value: z3.ExprRef) -> int | float | bool | str:
        if z3.is_bool(value):
            return z3.is_true(value)
        if z3.is_int_value(value) or z3.is_rational_value(value):
            return _numeric_from_model_value(value)
        if z3.is_string_value(value):
            return value.as_string()
        return str(value)

    def model_to_counterexample(
        model: z3.ModelRef,
        *,
        include_ret: bool,
    ) -> dict[str, int | float | bool | str]:
        counterexample: dict[str, int | float | bool | str] = {}
        for arg_name in case_spec.arg_types:
            value = model.eval(scope[arg_name], model_completion=True)
            counterexample[arg_name] = _model_value_to_python(value)
        if include_ret:
            ret_value = model.eval(scope["ret"], model_completion=True)
            counterexample["ret"] = _model_value_to_python(ret_value)
        return counterexample

    def _z3_expr_to_text(expr: Any) -> str:
        if hasattr(expr, "sexpr"):
            return str(expr.sexpr())
        return str(expr)

    # Step 1 from scheme: precondition mismatch check.
    pre_xor_solver = z3.Solver()
    pre_mismatch_check = z3.Xor(spec_assumptions, code_assumptions)
    pre_xor_solver.add(pre_mismatch_check)
    pre_xor_result = _check_with_status(pre_xor_solver)
    pre_xor_unknown = pre_xor_result == z3.unknown
    preconditions_mismatch = pre_xor_result == z3.sat
    preconditions_counterexample = None
    pre_mismatch_witness = None
    if preconditions_mismatch:
        pre_model = pre_xor_solver.model()
        preconditions_counterexample = model_to_counterexample(pre_model, include_ret=False)
        pre_mismatch_witness = model_to_counterexample(pre_model, include_ret=True)

    spec_implies_code_solver = z3.Solver()
    pre_spec_to_pre_code_implication = z3.Implies(spec_assumptions, code_assumptions)
    spec_implies_code_solver.add(z3.Not(pre_spec_to_pre_code_implication))
    spec_implies_code_status = _check_with_status(spec_implies_code_solver)
    spec_implies_code = spec_implies_code_status == z3.unsat
    pre_spec_implies_pre_code_witness = (
        model_to_counterexample(spec_implies_code_solver.model(), include_ret=True)
        if spec_implies_code_status == z3.sat
        else None
    )

    code_implies_spec_solver = z3.Solver()
    pre_code_to_pre_spec_implication = z3.Implies(code_assumptions, spec_assumptions)
    code_implies_spec_solver.add(z3.Not(pre_code_to_pre_spec_implication))
    code_implies_spec_status = _check_with_status(code_implies_spec_solver)
    code_implies_spec = code_implies_spec_status == z3.unsat
    pre_code_implies_pre_spec_witness = (
        model_to_counterexample(code_implies_spec_solver.model(), include_ret=True)
        if code_implies_spec_status == z3.sat
        else None
    )

    pre_solver_unknown = pre_xor_unknown or (
        spec_implies_code_status == z3.unknown or code_implies_spec_status == z3.unknown
    )

    failed_check = "none"
    if preconditions_mismatch:
        failed_check = "pre_mismatch_check"
    diagnostics: dict[str, object] = {
        "pre_mismatch": preconditions_mismatch,
        "pre_spec_implies_pre_code": spec_implies_code,
        "pre_code_implies_pre_spec": code_implies_spec,
        "pre_counterexample": preconditions_counterexample,
        "failed_check": failed_check,
        "post_well_formedness": post_well_formedness,
        "solver_status": {
            "pre_mismatch_check": str(pre_xor_result),
            "pre_spec_implies_pre_code": str(spec_implies_code_status),
            "pre_code_implies_pre_spec": str(code_implies_spec_status),
        },
        "solver_configuration": {
            "z3_version": z3.get_version_string(),
            "timeout_ms": _SOLVER_TIMEOUT_MS,
        },
        "solver_unknown_reasons": {
            name: reason
            for name, reason in {
                "pre_mismatch_check": _unknown_reason(pre_xor_solver, pre_xor_result),
                "pre_spec_implies_pre_code": _unknown_reason(spec_implies_code_solver, spec_implies_code_status),
                "pre_code_implies_pre_spec": _unknown_reason(code_implies_spec_solver, code_implies_spec_status),
            }.items()
            if reason is not None
        },
        "debug": {
            "formulas": {
                "pre_spec": _z3_expr_to_text(spec_assumptions),
                "pre_code": _z3_expr_to_text(code_assumptions),
                "common_pre": _z3_expr_to_text(z3.And(spec_assumptions, code_assumptions)),
                "post_spec": _z3_expr_to_text(spec_post),
                "post_code": _z3_expr_to_text(code_post),
            },
            "checks": {
                "pre_mismatch_check": _z3_expr_to_text(pre_mismatch_check),
                "post_mismatch_check": _z3_expr_to_text(
                    z3.Implies(
                        z3.And(spec_assumptions, code_assumptions),
                        z3.Xor(spec_post, code_post),
                    )
                ),
                "spec_post_implies_code_post": _z3_expr_to_text(
                    z3.Implies(
                        z3.And(z3.And(spec_assumptions, code_assumptions), spec_post),
                        code_post,
                    )
                ),
                "code_post_implies_spec_post": _z3_expr_to_text(
                    z3.Implies(
                        z3.And(z3.And(spec_assumptions, code_assumptions), code_post),
                        spec_post,
                    )
                ),
            },
            "witness_model": {
                "pre_mismatch_check": pre_mismatch_witness,
                "pre_spec_implies_pre_code": pre_spec_implies_pre_code_witness,
                "pre_code_implies_pre_spec": pre_code_implies_pre_spec_witness,
                "post_mismatch_check": None,
                "spec_post_implies_code_post": None,
                "code_post_implies_spec_post": None,
            },
        },
    }

    common_domain = z3.And(spec_assumptions, code_assumptions)

    # Step 1a from scheme:
    # if pre mismatch, classify PRE_CODE vs PRE_SPEC and finish early.
    if preconditions_mismatch:
        # XOR=sat proves a mismatch, but does not always determine its
        # direction. A single proven implication is enough to establish
        # strict strength; otherwise do not turn unknown into False.
        if (
            code_implies_spec_status == z3.unsat
            and spec_implies_code_status != z3.unsat
        ):
            reason = "case_pre_code"
        elif (
            spec_implies_code_status == z3.unsat
            and code_implies_spec_status != z3.unsat
        ):
            reason = "case_pre_spec"
        elif spec_implies_code_status == z3.sat and code_implies_spec_status == z3.sat:
            # Incomparable preconditions: retain Dualify's primary-label precedence.
            reason = "case_pre_code"
        else:
            return SmtResult(
                benchmark_id=case_spec.benchmark_id,
                equivalent=False,
                reason="solver_unknown",
                counterexample=preconditions_counterexample,
                diagnostics=diagnostics,
                well_formedness="solver_unknown_pre_direction",
            )
        return SmtResult(
            benchmark_id=case_spec.benchmark_id,
            equivalent=False,
            reason=reason,
            counterexample=preconditions_counterexample,
            diagnostics=diagnostics,
        )

    # If the pre-mismatch solver returned unknown, the precondition
    # comparison is undecided: we cannot rule out a hidden mismatch, so
    # refuse to proceed to the post-check (which would silently report
    # equivalent on a partially-decided domain).
    if pre_solver_unknown:
        return SmtResult(
            benchmark_id=case_spec.benchmark_id,
            equivalent=False,
            reason="solver_unknown",
            counterexample=None,
            diagnostics=diagnostics,
            well_formedness="solver_unknown_pre",
        )

    # Step 2 from scheme (evaluated only after pre checks are common):
    # post mismatch on common domain?
    post_mismatch_solver = z3.Solver()
    post_disagreement_implication = z3.Implies(common_domain, z3.Xor(spec_post, code_post))
    post_mismatch_solver.add(common_domain)
    post_mismatch_solver.add(post_disagreement_implication)
    post_mismatch_result = _check_with_status(post_mismatch_solver)
    post_mismatch = post_mismatch_result == z3.sat
    post_mismatch_unknown = post_mismatch_result == z3.unknown
    post_mismatch_counterexample = None
    post_mismatch_witness = None
    if post_mismatch:
        post_model = post_mismatch_solver.model()
        post_mismatch_counterexample = model_to_counterexample(post_model, include_ret=False)
        post_mismatch_witness = model_to_counterexample(post_model, include_ret=True)

    diagnostics["post_mismatch_on_common_pre"] = post_mismatch
    diagnostics["post_mismatch_counterexample"] = post_mismatch_counterexample
    solver_status = diagnostics.get("solver_status")
    if isinstance(solver_status, dict):
        solver_status["post_mismatch_check"] = str(post_mismatch_result)
    if post_mismatch_result == z3.unknown:
        diagnostics["solver_unknown_reasons"]["post_mismatch_check"] = _unknown_reason(
            post_mismatch_solver, post_mismatch_result
        )
    debug = diagnostics.get("debug")
    if isinstance(debug, dict):
        witness_model = debug.get("witness_model")
        if isinstance(witness_model, dict):
            witness_model["post_mismatch_check"] = post_mismatch_witness

    # An undecided post-mismatch check used to silently fall through to
    # `equivalent_no_mismatch`. That is unsound: Z3 returning unknown on
    # strings/sequences/nonlinear theories does not imply the formulas
    # agree. Surface it as solver_unknown instead.
    if post_mismatch_unknown:
        return SmtResult(
            benchmark_id=case_spec.benchmark_id,
            equivalent=False,
            reason="solver_unknown",
            counterexample=None,
            diagnostics=diagnostics,
            well_formedness="solver_unknown_post",
        )

    if not post_mismatch:
        # The XOR check said "no input where they disagree" -- but if the
        # postconditions range over disjoint variable sets, that verdict is
        # vacuous (the formulas are not even talking about the same thing).
        # Refuse to claim equivalence in that case.
        if post_well_formedness != "ok":
            return SmtResult(
                benchmark_id=case_spec.benchmark_id,
                equivalent=False,
                reason="vacuous_equivalence",
                counterexample=None,
                diagnostics=diagnostics,
                well_formedness=post_well_formedness,
            )
        return SmtResult(
            benchmark_id=case_spec.benchmark_id,
            equivalent=True,
            reason="equivalent_no_mismatch",
            counterexample=None,
            diagnostics=diagnostics,
        )

    # Step 3 from scheme (only after mismatch from step 2):
    # Implies(And(common_pre, post_spec), post_code) ?
    spec_post_implies_code_solver = z3.Solver()
    spec_to_code_implication = z3.Implies(z3.And(common_domain, spec_post), code_post)
    spec_post_implies_code_solver.add(z3.Not(spec_to_code_implication))
    spec_post_implies_code_status = _check_with_status(spec_post_implies_code_solver)
    spec_post_implies_code = spec_post_implies_code_status == z3.unsat
    spec_post_implies_code_witness = (
        model_to_counterexample(spec_post_implies_code_solver.model(), include_ret=True)
        if spec_post_implies_code_status == z3.sat
        else None
    )

    code_post_implies_spec_solver = z3.Solver()
    code_to_spec_implication = z3.Implies(z3.And(common_domain, code_post), spec_post)
    code_post_implies_spec_solver.add(z3.Not(code_to_spec_implication))
    code_post_implies_spec_status = _check_with_status(code_post_implies_spec_solver)
    code_post_implies_spec = code_post_implies_spec_status == z3.unsat
    code_post_implies_spec_witness = (
        model_to_counterexample(code_post_implies_spec_solver.model(), include_ret=True)
        if code_post_implies_spec_status == z3.sat
        else None
    )

    diagnostics["post_spec_implies_post_code_on_common_pre"] = spec_post_implies_code
    diagnostics["post_code_implies_post_spec_on_common_pre"] = code_post_implies_spec
    if not spec_post_implies_code:
        diagnostics["failed_check"] = "spec_post_implies_code_post"
    elif not code_post_implies_spec:
        diagnostics["failed_check"] = "code_post_implies_spec_post"
    else:
        diagnostics["failed_check"] = "post_mismatch_check"
    solver_status = diagnostics.get("solver_status")
    if isinstance(solver_status, dict):
        solver_status["spec_post_implies_code_post"] = str(spec_post_implies_code_status)
        solver_status["code_post_implies_spec_post"] = str(code_post_implies_spec_status)
    if spec_post_implies_code_status == z3.unknown:
        diagnostics["solver_unknown_reasons"]["spec_post_implies_code_post"] = _unknown_reason(
            spec_post_implies_code_solver, spec_post_implies_code_status
        )
    if code_post_implies_spec_status == z3.unknown:
        diagnostics["solver_unknown_reasons"]["code_post_implies_spec_post"] = _unknown_reason(
            code_post_implies_spec_solver, code_post_implies_spec_status
        )
    debug = diagnostics.get("debug")
    if isinstance(debug, dict):
        witness_model = debug.get("witness_model")
        if isinstance(witness_model, dict):
            witness_model["spec_post_implies_code_post"] = spec_post_implies_code_witness
            witness_model["code_post_implies_spec_post"] = code_post_implies_spec_witness

    # If either direction-check came back unknown, we know the
    # postconditions disagree (Step 2 returned sat) but we cannot tell
    # which side is stronger. Report solver_unknown rather than guess.
    if spec_post_implies_code_status == z3.unknown or code_post_implies_spec_status == z3.unknown:
        return SmtResult(
            benchmark_id=case_spec.benchmark_id,
            equivalent=False,
            reason="solver_unknown",
            counterexample=post_mismatch_counterexample,
            diagnostics=diagnostics,
            well_formedness="solver_unknown_post_direction",
        )

    reason = "case_post_code" if not spec_post_implies_code else "case_post_spec"
    return SmtResult(
        benchmark_id=case_spec.benchmark_id,
        equivalent=False,
        reason=reason,
        counterexample=post_mismatch_counterexample,
        diagnostics=diagnostics,
    )


def extraction_parseable(
    arg_types: dict[str, str],
    return_type: str,
    domain_constraints: list[str],
    postcondition: str,
    *,
    error_details: list[str] | None = None,
) -> bool:
    """Whether the given formulas survive Z3 type-checking under these arg types.

    Thin wrapper over :func:`is_parseable` for the extraction phases, which only
    have raw formula strings + signature types (not a full ``ExtractionResult``).
    Used to catch type-broken-but-syntactically-valid formulas (e.g.
    ``ForAll(...) / Length(...)`` or ``int <= ForAll(...)``) during validation,
    so they trigger the repair ladder instead of crashing Z3 later in ``p03``.
    """
    case_spec = CaseSpec(benchmark_id="", arg_types=arg_types, return_type=return_type)
    extraction = ExtractionResult(
        benchmark_id="",
        args=list(arg_types.keys()),
        return_type=return_type,
        domain_constraints=list(domain_constraints),
        postcondition=postcondition,
        confidence="",
        notes="",
    )
    return is_parseable(case_spec, extraction, error_details=error_details)


_EXTRACTION_SAT_TIMEOUT_MS = 2_000


@dataclass(frozen=True)
class FeasibilityResult:
    """Outcome of an existential Z3 check, separate from parsing."""

    status: Literal["sat", "unsat_pre", "unsat_contract", "unknown", "invalid"]
    reason: str = ""


def _contract_feasibility(constraints: list[Any], postcondition: Any) -> FeasibilityResult:
    """Check satisfiability, not functional correctness or gold equivalence."""
    solver = z3.Solver()
    solver.set("timeout", _EXTRACTION_SAT_TIMEOUT_MS)
    if constraints:
        solver.add(*constraints)
        if solver.check() == z3.unsat:
            return FeasibilityResult("unsat_pre")
    solver.add(postcondition)
    status = solver.check()
    if status == z3.unsat:
        return FeasibilityResult("unsat_contract")
    if status == z3.unknown:
        return FeasibilityResult("unknown", solver.reason_unknown()[:200])
    return FeasibilityResult("sat")


def _parse_contract(
    case_spec: CaseSpec,
    extraction: ExtractionResult,
    *,
    error_details: list[str] | None = None,
) -> tuple[list[Any], Any] | None:
    """Convert formulas to Z3 expressions, without running the solver."""
    scope: dict[str, Any] = {}
    known_names: set[str] = set()
    for arg_name, type_name in case_spec.arg_types.items():
        scope[arg_name] = _make_var(arg_name, type_name)
        known_names.add(arg_name)
    scope["ret"] = _make_var("ret", case_spec.return_type)
    known_names.add("ret")
    normalized_constraints = [
        _canonicalize_expression(c, case_spec.benchmark_id) for c in extraction.domain_constraints
    ]
    normalized_post = _canonicalize_expression(extraction.postcondition, case_spec.benchmark_id)
    normalized_extraction = ExtractionResult(
        benchmark_id=extraction.benchmark_id,
        args=extraction.args,
        return_type=extraction.return_type,
        domain_constraints=normalized_constraints,
        postcondition=normalized_post,
        confidence=extraction.confidence,
        notes=extraction.notes,
    )
    safety_issues = _validate_formula_safety(normalized_extraction)
    if safety_issues:
        if error_details is not None:
            error_details.extend(str(issue) for issue in safety_issues)
        return None
    _augment_scope_from_formulas(
        scope,
        known_names,
        [*normalized_constraints, normalized_post],
    )
    try:
        parsed_constraints = [
            _safe_eval(c, scope, case_spec.benchmark_id) for c in normalized_constraints
        ]
        parsed_post = _safe_eval(normalized_post, scope, case_spec.benchmark_id)
        return parsed_constraints, parsed_post
    except Exception as exc:
        if error_details is not None:
            error_details.append(f"{type(exc).__name__}: {str(exc)[:500]}")
        return None


def is_parseable(
    case_spec: CaseSpec,
    extraction: ExtractionResult,
    *,
    error_details: list[str] | None = None,
) -> bool:
    """Return whether the formulas can be parsed into well-typed Z3 expressions."""
    return _parse_contract(case_spec, extraction, error_details=error_details) is not None


def extraction_feasibility(
    arg_types: dict[str, str],
    return_type: str,
    domain_constraints: list[str],
    postcondition: str,
) -> FeasibilityResult:
    """Check whether a parsed extraction has any satisfying input and result.

    Not a proof of semantic correctness. An ``unknown`` result must not be
    treated as ``unsat``. Parsing stays independent of this solver check.
    """
    case_spec = CaseSpec(benchmark_id="", arg_types=arg_types, return_type=return_type)
    extraction = ExtractionResult(
        benchmark_id="",
        args=list(arg_types),
        return_type=return_type,
        domain_constraints=list(domain_constraints),
        postcondition=postcondition,
        confidence="",
        notes="",
    )
    parsed = _parse_contract(case_spec, extraction)
    if parsed is None:
        return FeasibilityResult("invalid", "Z3 expression parsing failed")
    return _contract_feasibility(*parsed)
