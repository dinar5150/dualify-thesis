import ast
import json
import re
from typing import TypedDict

from dualify.formula_parser import (
    ensure_ret_reference,
    extract_quantifier_binders,
    normalize_formula,
    salvage_valid_conjuncts,
    validate_formula,
)
from dualify.ollama_client import LLMClient
from dualify.phases.formula_prompt_rules import REPAIR_FORMULA_RULES, SAFE_SUBSET_EXTRA_RULES
from dualify.phases.p03_smt_checking import extraction_parseable
from dualify.types import ExtractionResult


def _typecheck_errors(
    domain_constraints: list[str],
    postcondition: str,
    arg_types: dict[str, str] | None,
    return_type: str,
) -> list[str]:
    """Z3 type-check gate: catch syntactically-valid but type-broken formulas."""
    if not arg_types:
        return []
    if extraction_parseable(arg_types, return_type, domain_constraints, postcondition):
        return []
    return ["postcondition/constraints fail Z3 type check"]

_INFIX_BOOL_PATTERN = re.compile(r"\s(And|Or)\s")
_RET_SELF_EQ_PATTERN = re.compile(r"^\s*ret\s*==\s*ret\s*$")
_RET_QUANTIFIER_EQ_PATTERN = re.compile(r"^\s*ret\s*==\s*(ForAll|Exists)\s*\(")
_QUANTIFIER_IN_CONCAT_PATTERN = re.compile(r"Concat\s*\(\s*(ForAll|Exists)\s*\(")
_ALLOWED_CALLS = {
    "And",
    "Or",
    "Not",
    "Implies",
    "If",
    "Abs",
    "Length",
    "Contains",
    "PrefixOf",
    "SuffixOf",
    "Concat",
    "Extract",
    "Unit",
    "ForAll",
    "Exists",
    "floor",
    "sqrt",
    "pow",
    "max",
    "min",
    "IsDigitString",
}


class _ExtractionPayload(TypedDict):
    args: list[str]
    return_type: str
    domain_constraints: list[str]
    postcondition: str
    confidence: str
    notes: str
    degraded: bool
    degraded_reason: str
    extraction_trace: dict[str, object]


def _to_str(value: object, default: str) -> str:
    return value if isinstance(value, str) else default


def _to_str_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


def _extract_signature_args(signature: str) -> list[str]:
    match = re.search(r"\((.*)\)", signature)
    if not match:
        return []
    raw_args = match.group(1).strip()
    if not raw_args:
        return []
    args: list[str] = []
    for chunk in raw_args.split(","):
        candidate = chunk.strip()
        if not candidate:
            continue
        name = candidate.split(":", 1)[0].strip()
        if name:
            args.append(name)
    return args


def _coerce_payload(payload: dict, allowed_args: list[str], return_type: str) -> _ExtractionPayload:
    return {
        "args": allowed_args,
        "return_type": _to_str(payload.get("return_type"), return_type),
        "domain_constraints": _to_str_list(payload.get("domain_constraints")),
        "postcondition": _to_str(payload.get("postcondition"), "ret == ret"),
        "confidence": _to_str(payload.get("confidence"), "unknown"),
        "notes": _to_str(payload.get("notes"), ""),
        "degraded": False,
        "degraded_reason": "",
        "extraction_trace": {},
    }


def _validate_expression(expr: str, allowed_names: set[str]) -> list[str]:
    normalized = normalize_formula(expr)
    errors: list[str] = []
    if _INFIX_BOOL_PATTERN.search(normalized):
        errors.append("uses infix And/Or")
    try:
        call_names = {
            node.func.id
            for node in ast.walk(ast.parse(normalized, mode="eval"))
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }
        unsupported = sorted(name for name in call_names if name not in _ALLOWED_CALLS)
        if unsupported:
            errors.append(f"unsupported function calls: {', '.join(unsupported)}")
    except Exception:
        pass
    extended = allowed_names | extract_quantifier_binders(normalized)
    errors.extend(validate_formula(normalized, extended))
    return errors


def _extract_self_symbols(text: str) -> set[str]:
    return {f"self_{name}" for name in re.findall(r"\bself\.([A-Za-z_][A-Za-z0-9_]*)\b", text)}


def _normalize_formula(expr: str) -> str:
    normalized = normalize_formula(expr)
    normalized = re.sub(r"\b([A-Za-z_][A-Za-z0-9_]*)_isdigit\(\)", r"IsDigitString(\1)", normalized)
    normalized = re.sub(r"\b(result|output|return_value)\b", "ret", normalized)
    return normalized


def _normalize_payload_formulas(payload: _ExtractionPayload) -> _ExtractionPayload:
    payload["domain_constraints"] = [
        _normalize_formula(expr) for expr in payload["domain_constraints"]
    ]
    payload["postcondition"] = ensure_ret_reference(_normalize_formula(payload["postcondition"]))
    return payload


def _validate_payload(
    payload: _ExtractionPayload,
    allowed_args: list[str],
    extra_symbols: set[str],
) -> list[str]:
    errors: list[str] = []
    allowed_names = set(allowed_args) | {"ret"} | extra_symbols

    if payload.get("args") != allowed_args:
        errors.append("args must exactly match signature arguments")

    postcondition = payload["postcondition"]
    if not postcondition.strip():
        errors.append("postcondition must be a non-empty string")
    else:
        post_errors = _validate_expression(postcondition, allowed_names)
        errors.extend([f"postcondition {item}" for item in post_errors])
        errors.extend([f"postcondition {item}" for item in _post_quality_issues(postcondition)])

    for constraint in payload["domain_constraints"]:
        constraint_errors = _validate_expression(constraint, allowed_names)
        errors.extend([f"domain constraint {item}" for item in constraint_errors])
    return errors


def _post_quality_issues(postcondition: str) -> list[str]:
    issues: list[str] = []
    normalized = normalize_formula(postcondition)
    if _RET_SELF_EQ_PATTERN.fullmatch(normalized):
        issues.append("must not be tautology `ret == ret`")
    if "ret" not in normalized:
        issues.append("must reference `ret`")
    if _RET_QUANTIFIER_EQ_PATTERN.match(normalized):
        issues.append("must not assign quantifier directly to ret")
    if _QUANTIFIER_IN_CONCAT_PATTERN.search(normalized):
        issues.append("must not pass quantifier into Concat")
    return issues


def _repair_payload(
    client: LLMClient,
    payload: _ExtractionPayload,
    errors: list[str],
    signature: str,
    return_type: str,
) -> dict:
    repair_prompt = f"""
You must fix invalid JSON extraction output.

Return strict JSON with keys:
{{
  "args": ["..."],
  "return_type": "{return_type}",
  "domain_constraints": ["..."],
  "postcondition": "...",
  "confidence": "low|medium|high",
  "notes": "short explanation"
}}

Rules:
- args must match signature args exactly (same names/order), never include ret.
- postcondition must use only signature args and ret.
- domain_constraints/postcondition must be SMT-compatible.
- Avoid language-specific shorthand (`and/or/not`, infix `A And B`).
- Never use `&` or `|`; use `And(...)` / `Or(...)`.
- Never output natural-language sentences in formulas.
- Do not use `all(...)`, `any(...)`, comprehensions, generator expressions, or `is`.
{REPAIR_FORMULA_RULES}

Signature:
{signature}

Errors to fix:
{json.dumps(errors, ensure_ascii=False)}

Current invalid JSON:
{json.dumps(payload, ensure_ascii=False)}
"""
    return client.generate_json(repair_prompt)


def _safe_subset_repair_payload(
    client: LLMClient,
    signature: str,
    return_type: str,
    informal_spec: str,
    extra_context: str,
) -> dict:
    prompt = f"""
You must output a conservative, syntactically valid extraction payload.

Return strict JSON with keys:
{{
  "args": ["..."],
  "return_type": "{return_type}",
  "domain_constraints": ["..."],
  "postcondition": "...",
  "confidence": "low|medium|high",
  "notes": "short explanation"
}}

Hard safety constraints:
- Use only this safe subset in expressions:
  And(...), Or(...), Not(...), Implies(...), If(...),
  ForAll([i], ...), Exists([i], ...),
  ==, !=, <, <=, >, >=, +, -, *, /, %, Length(...), Contains(...), Concat(...).
- Quantifier binders must be declared in the list argument, e.g. ForAll([k], ...).
- Do not use lambdas, comprehensions, or undeclared index variables.
- Do not introduce helper predicates.
- Use only signature args, normalized self fields (self_x), and ret.
- Prefer partial-but-valid constraints over invalid syntax.
- Never use `&` or `|`; use `And(...)` / `Or(...)`.
- Never output natural-language sentences in formulas.
- Do not use `all(...)`, `any(...)`, comprehensions, generator expressions, or `is`.
{REPAIR_FORMULA_RULES}
{SAFE_SUBSET_EXTRA_RULES}

Signature:
{signature}

Spec text:
{informal_spec}

Additional context:
{extra_context}
"""
    return client.generate_json(prompt)


def extract_spec_logic(
    client: LLMClient,
    benchmark_id: str,
    signature: str,
    informal_spec: str,
    return_type: str,
    extra_context: str = "",
    arg_types: dict[str, str] | None = None,
) -> ExtractionResult:
    prompt = f"""
You are translating an informal function spec into a logical formula.

Primary objective:
- produce a precise SMT-friendly contract (not vague properties).
- prefer exact semantics when derivable from the description/context.

Task:
1) infer argument names from signature
2) infer domain constraints (input validity assumptions only)
3) infer postcondition over args and ret

Output strict JSON with keys:
{{
  "args": ["..."],
  "return_type": "{return_type}",
  "domain_constraints": ["..."],
  "postcondition": "...",
  "confidence": "low|medium|high",
  "notes": "short explanation"
}}

Rules:
- HARD CONSTRAINTS (MUST):
  1) `args` must contain ONLY signature arguments in the same order.
  2) `args` MUST NOT contain `ret`.
  3) `postcondition` MUST reference only signature args and `ret`.
  4) Output ONE boolean expression in `postcondition`.
  5) Return JSON only, without markdown or comments.
- Use Z3/Python-style expressions.
- Allowed operators: And, Or, Not, Implies, If, ForAll, Exists, ==, !=, <, <=, >, >=,
  +, -, *, /, %, Abs, Length, Contains, PrefixOf, SuffixOf, Concat
- Quantifiers: write ForAll([k], body) and Exists([k], body); bind every index in the list.
- `ret` means the return value.
- Use only argument names from signature and normalized object fields like `self_code`.
- Normalize object attributes: `self.code` -> `self_code`.
- In formulas, allowed variable names are ONLY args, normalized object fields and `ret`.
- Keep expressions compact and deterministic.
- If description does not explicitly restrict input domain, use `domain_constraints: []`.
- domain_constraints are input-validity assumptions only, not branch predicates.
- Postcondition must encode behavior on valid inputs (exactly when possible).
- Prefer built-in SMT operators/functions; introduce helper predicates only if unavoidable.
- Never call the function name in formulas.
- Avoid language-specific shorthand (`and/or/not`, `&&`, `||`, `->`, `=>`, semicolon chains).
- Never use `&` or `|`; use `And(...)` / `Or(...)`.
- Never output natural-language sentences in formulas.
- Do not use `all(...)`, `any(...)`, comprehensions, generator expressions, or `is`.
- `floor(x)` is allowed and interpreted via SMT floor.
- `sqrt(x)` and `pow(x, y)` are allowed when SMT-compatible.
- Forbidden tokens in formulas: `lambda` and any braces.
- Self-check before final JSON:
  - `args` excludes `ret`
  - Expressions are syntactically valid and SMT-compatible
  - `postcondition` uses only args and `ret`

Universal examples:
- exact arithmetic mapping: `ret == a * b + c`
- boolean predicate: `ret == (x > 0)`
- piecewise behavior: `ret == If(cond, v1, v2)`
- sequence/string property: `And(Length(ret) == 1, Contains(ret[0], "1"))`

Signature:
{signature}

Informal specification:
{informal_spec}

Additional context:
{extra_context}
"""
    allowed_args = _extract_signature_args(signature)
    extra_symbols = _extract_self_symbols(informal_spec + "\n" + extra_context)
    try:
        raw_payload = client.generate_json(prompt)
    except Exception:
        raw_payload = {}
    payload = _normalize_payload_formulas(_coerce_payload(raw_payload, allowed_args, return_type))
    errors = _validate_payload(payload, allowed_args, extra_symbols)
    if not errors:
        errors = _typecheck_errors(
            payload["domain_constraints"], payload["postcondition"], arg_types, return_type
        )
    payload["extraction_trace"]["initial"] = {
        "domain_constraints": list(payload["domain_constraints"]),
        "postcondition": payload["postcondition"],
        "errors": list(errors),
    }
    if errors:
        try:
            repaired_raw = _repair_payload(client, payload, errors, signature, return_type)
        except Exception:
            repaired_raw = {}
        repaired_payload = _normalize_payload_formulas(
            _coerce_payload(repaired_raw, allowed_args, return_type)
        )
        repair_errors = _validate_payload(repaired_payload, allowed_args, extra_symbols)
        if not repair_errors:
            repair_errors = _typecheck_errors(
                repaired_payload["domain_constraints"],
                repaired_payload["postcondition"],
                arg_types,
                return_type,
            )
        payload["extraction_trace"]["repair"] = {
            "domain_constraints": list(repaired_payload["domain_constraints"]),
            "postcondition": repaired_payload["postcondition"],
            "errors": list(repair_errors),
        }
        if not repair_errors:
            payload = repaired_payload
        else:
            try:
                safe_raw = _safe_subset_repair_payload(
                    client=client,
                    signature=signature,
                    return_type=return_type,
                    informal_spec=informal_spec,
                    extra_context=extra_context,
                )
            except Exception:
                safe_raw = {}
            safe_payload = _normalize_payload_formulas(
                _coerce_payload(safe_raw, allowed_args, return_type)
            )
            safe_errors = _validate_payload(safe_payload, allowed_args, extra_symbols)
            if not safe_errors:
                safe_errors = _typecheck_errors(
                    safe_payload["domain_constraints"],
                    safe_payload["postcondition"],
                    arg_types,
                    return_type,
                )
            payload["extraction_trace"]["safe_repair"] = {
                "domain_constraints": list(safe_payload["domain_constraints"]),
                "postcondition": safe_payload["postcondition"],
                "errors": list(safe_errors),
            }
            if not safe_errors:
                safe_payload["confidence"] = "low"
                safe_payload["notes"] = "Recovered via safe-subset repair after validation failure."
                safe_payload["degraded"] = True
                safe_payload["degraded_reason"] = "recovered_safe_subset"
                safe_payload["extraction_trace"] = dict(payload["extraction_trace"])
                payload = safe_payload
            else:
                allowed_names = set(allowed_args) | {"ret"} | extra_symbols

                def _is_valid_conjunct(expr: str, _names: set[str] = allowed_names) -> bool:
                    if _validate_expression(expr, _names) or _post_quality_issues(expr):
                        return False
                    return not _typecheck_errors([], expr, arg_types, return_type)

                salvaged = ""
                for candidate in (
                    safe_payload["postcondition"],
                    repaired_payload["postcondition"],
                    payload["postcondition"],
                ):
                    salvaged = salvage_valid_conjuncts(candidate, _is_valid_conjunct)
                    if salvaged:
                        break
                if salvaged:
                    payload["postcondition"] = salvaged
                    payload["domain_constraints"] = [
                        c
                        for c in safe_payload["domain_constraints"]
                        if not _validate_expression(c, allowed_names)
                    ]
                    payload["confidence"] = "low"
                    payload["notes"] = "Recovered via conjunct salvage after repair failure."
                    payload["degraded"] = True
                    payload["degraded_reason"] = "salvaged_partial_postcondition"
                else:
                    payload["notes"] = (
                        "Auto-sanitized after validation failure. "
                        + f"Errors: {', '.join(safe_errors[:3])}"
                    )
                    payload["confidence"] = "low"
                    payload["domain_constraints"] = []
                    payload["postcondition"] = "ret == ret"
                    payload["degraded"] = True
                    payload["degraded_reason"] = "sanitize_after_validation_failure"
    payload["extraction_trace"]["final"] = {
        "domain_constraints": list(payload["domain_constraints"]),
        "postcondition": payload["postcondition"],
        "degraded": payload["degraded"],
        "degraded_reason": payload["degraded_reason"],
    }

    return ExtractionResult(
        benchmark_id=benchmark_id,
        args=payload["args"],
        return_type=payload["return_type"],
        domain_constraints=payload["domain_constraints"],
        postcondition=payload["postcondition"],
        confidence=payload["confidence"],
        notes=payload["notes"],
        degraded=payload["degraded"],
        degraded_reason=payload["degraded_reason"],
        extraction_trace=payload["extraction_trace"],
    )
