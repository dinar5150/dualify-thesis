"""Reproduce the offline oracle audit on synthetic controls and frozen DEV finals."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import tarfile
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
import z3

from dualify.gold_scoring import _gold_formulas
from dualify.phases import p03_smt_checking as native
from dualify.types import ExtractionResult

ROOT = Path(__file__).resolve().parents[2]
ARCHIVE = ROOT / "docs/rq1/artifacts/dev-2026-11-22-vpn.tar.gz"
MANIFEST = ROOT / "docs/rq1/benchmark-manifest.json"
OUTPUT = ROOT / "docs/rq1/research/artifacts/oracle-audit.json"
TIMEOUT_MS = 5000
STATUS = dict[str, str]
FORMULA = tuple[list[str], str]


@dataclass
class Terms:
    scope: dict[str, Any]
    gold_pre: z3.BoolRef
    gold_post: z3.BoolRef
    candidate_pre: z3.BoolRef
    candidate_post: z3.BoolRef


def query(expression: z3.BoolRef, timeout: int = TIMEOUT_MS) -> STATUS:
    solver = z3.Solver()
    solver.set(timeout=timeout)
    solver.add(expression)
    outcome = solver.check()
    status = {"status": str(outcome)}
    if outcome == z3.unknown:
        status["reason"] = solver.reason_unknown()
    return status


def boolean(term: Any) -> z3.BoolRef:
    if isinstance(term, bool):
        return z3.BoolVal(term)
    if not z3.is_bool(term):
        raise ValueError("Expected a Boolean formula")
    return term


def translate(
    case: native.CaseSpec, gold: FORMULA, candidate: FORMULA, *, typed_tuple: bool = False,
) -> Terms:
    # Hold the production formula parser fixed. The audit keeps every precondition conjunct.
    scope = {name: native._make_var(name, sort) for name, sort in case.arg_types.items()}
    scope["ret"] = native._make_var("ret", case.return_type)
    if typed_tuple:
        if case.return_type != "Tuple[int, int, str]":
            raise ValueError("Tuple ablation applies only to the DEV mixed tuple signature")
        sort, _, projections = z3.TupleSort(
            "ParseInputResult", [z3.IntSort(), z3.IntSort(), z3.StringSort()],
        )
        scope["ret"] = z3.Const("ret", sort)
        for i, projection in enumerate(projections):
            scope[f"_tuple_component_{i}"] = projection(scope["ret"])

    def canonical(expression: str) -> str:
        expression = native._canonicalize_expression(expression, case.benchmark_id)
        if typed_tuple:
            expression = re.sub(r"\bret\[([012])\]", r"_tuple_component_\1", expression)
        return expression

    gold_pre = [canonical(formula) for formula in gold[0]]
    candidate_pre = [canonical(formula) for formula in candidate[0]]
    gold_post = canonical(gold[1])
    candidate_post = canonical(candidate[1])
    native._augment_scope_from_formulas(
        scope, set(scope), [*gold_pre, *candidate_pre, gold_post, candidate_post],
    )

    def parse(expression: str) -> z3.BoolRef:
        return boolean(native._safe_eval(expression, scope, case.benchmark_id))

    return Terms(
        scope, z3.And(*map(parse, gold_pre)), parse(gold_post),
        z3.And(*map(parse, candidate_pre)), parse(candidate_post),
    )


def any_counterexample(*statuses: str) -> str:
    if "sat" in statuses:
        return "refuted"
    if "unknown" in statuses:
        return "undecided"
    return "proved"


def audit(terms: Terms) -> dict[str, Any]:
    gp, gq = terms.gold_pre, terms.gold_post
    cp, cq = terms.candidate_pre, terms.candidate_post
    common = z3.And(gp, cp)
    checks = {
        "pre_xor": query(z3.Xor(gp, cp)),
        "gold_domain": query(gp),
        "candidate_domain": query(cp),
        # Nested existential over results checks whether some admissible input
        # has no allowed result. Other free variables remain shared parameters.
        "candidate_infeasible_input": query(z3.And(cp, z3.Not(z3.Exists(
            [terms.scope["ret"]], cq,
        )))),
        "candidate_can_exclude_output": query(z3.And(cp, z3.Not(cq))),
    }
    status = {key: value["status"] for key, value in checks.items()}
    if status["pre_xor"] != "sat":
        checks["post_xor_on_overlap"] = query(z3.And(common, z3.Xor(gq, cq)))
    post_xor = checks.get("post_xor_on_overlap", {"status": "unknown"})["status"]
    direct = any_counterexample(status["pre_xor"], post_xor)

    # Refinement uses the entire reference domain. We keep reverse implication
    # on the same domain as a diagnostic for additional generated guarantees.
    checks["gold_input_rejected"] = query(z3.And(gp, z3.Not(cp)))
    checks["gold_post_violated"] = query(z3.And(gp, cq, z3.Not(gq)))
    checks["additional_candidate_post"] = query(z3.And(gp, gq, z3.Not(cq)))
    status = {key: value["status"] for key, value in checks.items()}
    refinement = any_counterexample(status["gold_input_rejected"], status["gold_post_violated"])
    # Check feasibility over the reference domain separately when equivalence
    # cannot establish that this equals the candidate's advertised domain.
    if status["pre_xor"] == "unsat":
        infeasible_gold_input = status["candidate_infeasible_input"]
    elif refinement == "proved":
        checks["candidate_infeasible_gold_input"] = query(
            z3.And(gp, z3.Not(z3.Exists([terms.scope["ret"]], cq))),
        )
        infeasible_gold_input = checks["candidate_infeasible_gold_input"]["status"]
    else:
        infeasible_gold_input = "unknown"

    def non_vacuity(domain: str, impossible: str, informative: str) -> str:
        if domain == "unsat" or impossible == "sat" or informative == "unsat":
            return "refuted"
        if "unknown" in (domain, impossible, informative):
            return "undecided"
        return "proved"

    health = non_vacuity(
        status["candidate_domain"],
        status["candidate_infeasible_input"],
        status["candidate_can_exclude_output"],
    )
    if refinement == "proved":
        # Even if the assertions can restrict output beyond the gold domain,
        # the refinement criterion requires information on the reference domain.
        checks["candidate_can_exclude_gold_output"] = query(z3.And(gp, z3.Not(cq)))
        refinement = non_vacuity(
            status["gold_domain"],
            infeasible_gold_input,
            checks["candidate_can_exclude_gold_output"]["status"],
        )
    return {
        "direct_equivalence": direct,
        "candidate_non_vacuity": health,
        "nonvacuous_equivalence": (
            health if direct == "proved" else direct
        ),
        "nonvacuous_refinement": refinement,
        "checks": checks,
    }


def extraction(case: native.CaseSpec, formula: FORMULA) -> ExtractionResult:
    return ExtractionResult(
        case.benchmark_id, list(case.arg_types), case.return_type,
        formula[0], formula[1], "", "",
    )


def native_outcome(case: native.CaseSpec, gold: FORMULA, candidate: FORMULA) -> dict[str, Any]:
    reference = extraction(case, gold)
    generated = extraction(case, candidate)
    result = native.check_equivalence(case, reference, generated)
    return {
        "equivalent": result.equivalent,
        "reason": result.reason,
        "well_formedness": result.well_formedness,
        "solver_status": (result.diagnostics or {}).get("solver_status"),
        "candidate_parseable_with_native_guard": native.is_parseable(case, generated),
    }


def controls() -> list[dict[str, Any]]:
    x, y, ret, i, j = z3.Ints("x y ret i j")
    true = z3.BoolVal(True)
    case = native.CaseSpec("oracle_audit", {"x": "int", "y": "int"}, "int")
    cases = [
        ("identical", [], "ret == x", [], "ret == x", true, ret == x, true, ret == x),
        ("commutativity", [], "ret == x + y", [], "ret == y + x",
         true, ret == x + y, true, ret == y + x),
        ("equivalent_on_pre", ["x >= 0"], "ret == Abs(x)", ["x >= 0"], "ret == x",
         x >= 0, ret == z3.Abs(x), x >= 0, ret == x),
        ("vocabulary_heuristic", ["x == y"], "ret == x + 1", ["x == y"], "ret == y + 1",
         x == y, ret == x + 1, x == y, ret == y + 1),
        ("stronger_post", [], "ret >= x", [], "ret == x",
         true, ret >= x, true, ret == x),
        ("weaker_post", [], "ret == x", [], "ret >= x",
         true, ret == x, true, ret >= x),
        ("incompatible_posts", [], "ret == x", [], "ret == x + 1",
         true, ret == x, true, ret == x + 1),
        ("partial_contract", [], "ret == x", [], "Implies(x >= 0, ret == x)",
         true, ret == x, true, z3.Implies(x >= 0, ret == x)),
        ("wider_pre", ["x >= 0"], "ret == x", [], "ret == x",
         x >= 0, ret == x, true, ret == x),
        ("narrower_pre", [], "ret == x", ["x >= 0"], "ret == x",
         true, ret == x, x >= 0, ret == x),
        ("tautology", [], "ret == ret", [], "ret == ret",
         true, ret == ret, true, ret == ret),
        ("contradiction", [], "ret != ret", [], "ret != ret",
         true, ret != ret, true, ret != ret),
        ("feasible_for_some_inputs_only", [], "ret == x", [], "And(x >= 0, ret == x)",
         true, ret == x, true, z3.And(x >= 0, ret == x)),
        ("unreachable_pre", ["And(x >= 0, x < 0)"], "ret == x",
         ["And(x >= 0, x < 0)"], "ret == x + 1",
         z3.And(x >= 0, x < 0), ret == x, z3.And(x >= 0, x < 0), ret == x + 1),
        ("discarded_pre_conjunction", ["x >= 0", "x < 0"], "ret == x", [], "ret == x",
         z3.And(x >= 0, x < 0), ret == x, true, ret == x),
        ("alpha_renaming", [], "ForAll([i], Implies(i >= 0, ret + i >= x))",
         [], "ForAll([j], Implies(j >= 0, ret + j >= x))",
         true, z3.ForAll([i], z3.Implies(i >= 0, ret + i >= x)),
         true, z3.ForAll([j], z3.Implies(j >= 0, ret + j >= x))),
        ("guard_false_positive", [], "ret == x + y - 2", [], "ret == x + (y - 2)",
         true, ret == x + y - 2, true, ret == x + (y - 2)),
        ("nonlinear_identity", [], "ret == (x + y) ** 2",
         [], "ret == x * x + 2 * x * y + y * y",
         true, ret == (x + y) ** 2, true, ret == x * x + 2 * x * y + y * y),
    ]
    rows = []
    for name, gpre, gpost, cpre, cpost, gp, gq, cp, cq in cases:
        direct = audit(Terms({"x": x, "y": y, "ret": ret}, gp, gq, cp, cq))
        rows.append({
            "case": name, "gold": (gpre, gpost), "candidate": (cpre, cpost),
            "native": native_outcome(case, (gpre, gpost), (cpre, cpost)), "independent": direct,
        })

    s, rstr = z3.Strings("s ret")
    seq_sort = z3.SeqSort(z3.IntSort())
    xs, rseq = z3.Consts("xs ret", seq_sort)
    for name, spec, formulas, scope, posts in (
        (
            "string_prefix", native.CaseSpec("oracle_audit", {"s": "str"}, "str"),
            ("ret == Concat(s, 'a')", "And(PrefixOf(s, ret), ret == Concat(s, 'a'))"),
            {"ret": rstr, "s": s},
            (rstr == z3.Concat(s, "a"), z3.And(z3.PrefixOf(s, rstr), rstr == z3.Concat(s, "a"))),
        ),
        (
            "sequence_length", native.CaseSpec("oracle_audit", {"xs": "List[int]"}, "List[int]"),
            ("Length(ret) == Length(xs)", "Length(ret) - Length(xs) == 0"),
            {"ret": rseq, "xs": xs},
            (z3.Length(rseq) == z3.Length(xs), z3.Length(rseq) - z3.Length(xs) == 0),
        ),
    ):
        rows.append({
            "case": name, "gold": ([], formulas[0]), "candidate": ([], formulas[1]),
            "native": native_outcome(spec, ([], formulas[0]), ([], formulas[1])),
            "independent": audit(Terms(scope, true, posts[0], true, posts[1])),
        })

    return rows


def model_mismatches() -> list[dict[str, Any]]:
    x, y = z3.Ints("x y")
    xs = z3.Const("xs", z3.SeqSort(z3.IntSort()))
    s = z3.String("s")
    scope = {"x": x, "y": y, "xs": xs, "s": s}
    rows = []
    empty_list: list[int] = []
    cases = (
        ("negative_modulus", "x % y", [x == 5, y == -3], 5 % -3),
        ("negative_floor_division", "x // y", [x == 5, y == -3], 5 // -3),
        ("integer_true_division", "x / y", [x == 3, y == 2], 3 / 2),
        ("negative_sequence_index", "xs[-1]", [xs == z3.Unit(z3.IntVal(7))], [7][-1]),
        ("empty_digit_string", "IsDigitString(s)", [s == ""], "".isdigit()),
        ("unicode_digit_string", "IsDigitString(s)", [s == "²"], "²".isdigit()),
        ("none_is_not_empty_sequence", "xs == None", [xs == z3.Empty(xs.sort())],
         empty_list is None),
    )
    for name, formula, facts, python_value in cases:
        translated = native._safe_eval(formula, scope, "oracle_audit")
        if isinstance(python_value, float):
            # Avoid Z3Py casting a non-integer literal to the Int sort.
            translated = z3.ToReal(translated)
        rows.append({
            "name": name, "formula": formula, "smt": translated.sexpr(),
            "facts": [fact.sexpr() for fact in facts], "python_value": python_value,
            "smt_agrees_with_python": query(z3.And(*facts, translated == python_value)),
            "smt_disagrees_with_python": query(z3.And(*facts, translated != python_value)),
        })
    rows.append({
        "name": "unsupported_operation",
        "native": native_outcome(
            native.CaseSpec("oracle_audit", {"xs": "List[int]"}, "int"),
            ([], "ret == sum(xs)"), ([], "ret == sum(xs)"),
        ),
        "independent_finite_instance": query(
            z3.And(xs == z3.Concat(z3.Unit(z3.IntVal(2)), z3.Unit(z3.IntVal(3))),
                   xs[0] + xs[1] != 5),
        ),
    })
    rows.append({
        "name": "modular_power_sort_error",
        "native": native_outcome(
            native.CaseSpec("oracle_audit", {"x": "int", "y": "int"}, "int"),
            ([], "ret == pow(x, y, 3)"), ([], "ret == pow(x, y, 3)"),
        ),
        "python_value_at_2_3": pow(2, 3, 3),
    })
    return rows


def timeout_control() -> dict[str, Any]:
    # A small unsatisfiable pigeonhole instance, varied by wall-clock budget.
    n = 8
    placements = [[z3.Bool(f"p_{i}_{j}") for j in range(n - 1)] for i in range(n)]
    impossible = z3.And(
        *(z3.Or(row) for row in placements),
        *(z3.AtMost(*column, 1) for column in zip(*placements, strict=True)),
    )
    arithmetic = z3.Real("a")
    variable_exponent = 2**arithmetic == 3
    return {
        "same_formula_budget_sweep_ms": {
            str(ms): query(impossible, ms) for ms in (1, 100, TIMEOUT_MS)
        },
        "variable_exponent_smt": variable_exponent.sexpr(),
        "variable_exponent_status": query(variable_exponent),
    }


def load_dev() -> tuple[dict[str, dict], list[dict], dict[str, dict]]:
    manifest = json.loads(MANIFEST.read_text())
    records = {row["benchmark_id"]: row for row in manifest["cases"] if row["split"] == "dev"}
    with tarfile.open(ARCHIVE) as archive:
        finals = []
        for member in archive:
            if "/pools/" in member.name and member.name.endswith("/result.json"):
                with archive.extractfile(member) as file:
                    result = json.load(file)
                assert result["status"] == "completed"
                assert result["extraction"]["benchmark_id"] in records
                finals.append(result)
        with archive.extractfile("rq1-dev-vpn-2026-11-22/offline-diagnostics.json") as file:
            scores = {row["slot_id"]: row for row in json.load(file)["scores"]}
    expected_slots = {
        f"{bid}:{channel}:{arm}:{index}"
        for bid in records for channel in ("spec", "code")
        for arm, index in [("baseline", 0), *(("treatment", i) for i in range(1, 5))]
    }
    assert {final["slot_id"] for final in finals} == scores.keys() == expected_slots
    assert len(finals) == len(expected_slots)
    for record in records.values():
        for key in ("input", "gold"):
            path = ROOT / record[f"{key}_path"]
            assert hashlib.sha256(path.read_bytes()).hexdigest() == record[f"{key}_sha256"]
    return records, sorted(finals, key=lambda row: row["slot_id"]), scores


def audit_saved(
    records: dict[str, dict], finals: list[dict], scores: dict[str, dict],
) -> list[dict]:
    rows = []
    cache = {}
    for final in finals:
        slot = final["slot_id"]
        generated = final["extraction"]
        bid = generated["benchmark_id"]
        reference = yaml.safe_load((ROOT / records[bid]["gold_path"]).read_text())
        case = native.CaseSpec(bid, reference["arg_types"], reference["return_type"])
        gold = _gold_formulas(reference)
        candidate = (generated["domain_constraints"], generated["postcondition"])
        key = (bid, tuple(candidate[0]), candidate[1])
        if key not in cache:
            try:
                alternative = audit(translate(case, gold, candidate))
            except (z3.Z3Exception, ValueError, TypeError, SyntaxError, NameError) as error:
                alternative = {"parse_error": str(error)}
            result = {"direct_same_translation": alternative}
            if reference["qualname"] == "parse_input":
                result["direct_typed_tuple"] = audit(
                    translate(case, gold, candidate, typed_tuple=True),
                )
            cache[key] = result
        rows.append({
            "slot_id": slot, "task": reference["qualname"], "channel": final["channel"],
            "candidate": candidate, "historical_status": scores[slot]["status"],
            "historical_reason": scores[slot]["reason"], **cache[key],
        })
    return rows


def sequence(values: list[str] | list[int], sort: z3.SortRef) -> z3.ExprRef:
    if not values:
        return z3.Empty(sort)
    units = [
        z3.Unit(z3.StringVal(value) if isinstance(value, str) else z3.IntVal(value))
        for value in values
    ]
    return z3.Concat(*units) if len(units) > 1 else units[0]


def unfold_csv_at_length_one(
    expression: z3.BoolRef, outside_queries: list[dict[str, Any]],
) -> z3.BoolRef:
    if z3.is_and(expression):
        return z3.And(*(unfold_csv_at_length_one(child, outside_queries)
                        for child in expression.children()))
    if not z3.is_quantifier(expression):
        return expression
    assert expression.is_forall() and expression.num_vars() == 1
    index = z3.FreshInt("index")
    body = expression.body()
    outside = z3.And(index != 0, z3.Not(z3.substitute_vars(body, index)))
    outside_result = query(outside)
    outside_queries.append({"smt": outside.sexpr(), "result": outside_result})
    if outside_result["status"] == "unsat":
        return z3.substitute_vars(body, z3.IntVal(0))
    # A violating index proves the universal false on this concrete input.
    at_length = z3.substitute_vars(body, z3.IntVal(1))
    assert query(at_length)["status"] == "unsat"
    outside_queries.append({"smt": at_length.sexpr(), "result": query(at_length)})
    return z3.BoolVal(False)


def dev_gold_witnesses(records: dict[str, dict], rows: list[dict]) -> dict[str, Any]:
    def load(name: str) -> tuple[native.CaseSpec, FORMULA, Any]:
        bid, record = next((k, v) for k, v in records.items() if k.split("::")[-1] == name)
        gold = yaml.safe_load((ROOT / record["gold_path"]).read_text())
        # Execute checked-in DEV sources only. Future annotations avoid imports
        # used exclusively in lifted type hints.
        source = "from __future__ import annotations\n" + (ROOT / record["input_path"]).read_text()
        namespace: dict[str, Any] = {}
        exec(compile(source, str(record["input_path"]), "exec", dont_inherit=True), namespace)
        return native.CaseSpec(bid, gold["arg_types"], gold["return_type"]), _gold_formulas(gold), (
            namespace[name]
        )

    parse_case, parse_gold, parse_fn = load("parse_input")
    parse_rows = []
    parse_terms = translate(parse_case, parse_gold, parse_gold, typed_tuple=True)
    lines = parse_terms.scope["lines"]
    ret = parse_terms.scope["ret"]
    assert ret.sort().constructor(0).arity() == 3
    wrong_width = translate(
        parse_case, parse_gold, (parse_gold[0], parse_gold[1].replace(
            "ret[0] == Length(lines[0])", "ret[0] == Length(lines[0]) + 1",
        )), typed_tuple=True,
    )
    assert not wrong_width.gold_post.eq(wrong_width.candidate_post)
    for source in (["..", "##"], ["..", "#"]):
        result = parse_fn(source)
        width, height, content = result
        ret_value = ret.sort().constructor(0)(width, height, z3.StringVal(content))
        facts = z3.And(lines == sequence(source, lines.sort()), ret == ret_value)
        parse_rows.append({
            "input": source, "python_result": result,
            "gold_pre": query(z3.And(facts, z3.Not(parse_terms.gold_pre))),
            "gold_post": query(z3.And(facts, z3.Not(parse_terms.gold_post))),
            "queries_are_counterexamples": True,
        })

    csv_case, csv_gold, csv_fn = load("csv_first_column")
    csv_source = ["a,b"]
    csv_results = []
    for row in rows:
        if row["task"] != "csv_first_column":
            continue
        terms = translate(csv_case, csv_gold, row["candidate"])
        lines, ret = terms.scope["lines"], terms.scope["ret"]
        input_value = sequence(csv_source, lines.sort())
        wrong_result = sequence(["x"], ret.sort())
        if row["channel"] == "spec":
            witness = z3.And(
                terms.gold_pre, terms.candidate_pre, terms.candidate_post, z3.Not(terms.gold_post),
            )
            witness_kind = "post_xor"
        else:
            witness = z3.And(terms.gold_pre, z3.Not(terms.candidate_pre))
            witness_kind = "pre_xor"
        ground = z3.substitute(witness, (lines, input_value), (ret, wrong_result))
        outside_queries: list[dict[str, Any]] = []
        # Unfold each universal only after verifying an exhaustive local case.
        # This converts the concrete witness into decidable sequence operations.
        ground_terms = [
            unfold_csv_at_length_one(
                z3.substitute(term, (lines, input_value), (ret, wrong_result)), outside_queries,
            )
            for term in (terms.gold_pre, terms.gold_post, terms.candidate_pre)
        ]
        grounded_gp, grounded_gq, grounded_cp = ground_terms
        grounded_cq = z3.substitute(terms.candidate_post, (lines, input_value), (ret, wrong_result))
        if witness_kind == "post_xor":
            unrolled = z3.And(grounded_gp, grounded_cp, grounded_cq, z3.Not(grounded_gq))
        else:
            unrolled = z3.And(grounded_gp, z3.Not(grounded_cp))
        csv_results.append({
            "slot_id": row["slot_id"], "witness": witness_kind,
            "ground_quantified_query": query(ground),
            "outside_index_checks": outside_queries,
            "query": query(unrolled), "smt": unrolled.sexpr(),
        })
    # General proof of the dead CSV code domain: instantiate its actual ForAll
    # at Length(lines), then discharge the resulting necessary condition.
    code_row = next(r for r in rows if r["task"] == "csv_first_column" and r["channel"] == "code")
    code_terms = translate(csv_case, csv_gold, code_row["candidate"])
    code_pre = code_terms.candidate_pre.arg(0)
    lines = code_terms.scope["lines"]
    necessary = z3.substitute_vars(code_pre.body(), z3.Length(lines))
    csv_dead_domain = {"instantiation": necessary.sexpr(), "result": query(necessary)}

    average_case, average_gold, average_fn = load("average")
    average_terms = translate(average_case, average_gold, average_gold)
    numbers, ret = average_terms.scope["numbers"], average_terms.scope["ret"]
    average_facts = z3.And(
        numbers == z3.Concat(z3.Unit(z3.RealVal(0)), z3.Unit(z3.RealVal(2))), ret == 0,
    )
    average_underspecification = query(
        z3.And(average_facts, average_terms.gold_pre, average_terms.gold_post),
    )

    expression_case, expression_gold, expression_fn = load("extract_expression")
    expression_terms = translate(expression_case, expression_gold, expression_gold)
    expression = "(()"
    try:
        expression_fn(expression)
    except Exception as error:
        expression_exception = {"type": type(error).__name__, "message": str(error)}
    else:
        raise AssertionError("The DEV exception witness did not reproduce")
    exact_substring_input = "(a)"
    exact_substring_output = expression_fn(exact_substring_input)
    expression_row = next(
        row for row in rows if row["slot_id"].endswith(":extract_expression:code:treatment:4")
    )
    wrong_substring = translate(expression_case, expression_gold, expression_row["candidate"])
    refinements_against_code = query(z3.And(
        wrong_substring.scope["expr"] == exact_substring_input,
        wrong_substring.scope["ret"] == exact_substring_output,
        wrong_substring.gold_pre, wrong_substring.gold_post, wrong_substring.candidate_pre,
        z3.Not(wrong_substring.candidate_post),
    ))

    _, _, solve_fn = load("solve")
    solve_input, preamble = [5, 5, 10], 2
    position_pairs = [
        (i, j) for i in range(preamble) for j in range(preamble)
        if i != j and solve_input[i] + solve_input[j] == solve_input[preamble]
    ]

    duration_case, duration_gold, duration_fn = load("duration")
    duration_candidate = next(
        row["candidate"] for row in rows if row["task"] == "Entry.duration"
        and row["channel"] == "code"
    )
    duration_terms = translate(duration_case, duration_gold, duration_candidate)
    start = duration_terms.scope["self_start"]
    end = duration_terms.scope["self_end"]
    duration_result = z3.IntVal(duration_fn(2, 1))
    duration_binding = z3.And(start == 2, end == 1,
                              duration_terms.scope["ret"] == duration_result)

    departure_case, departure_gold, departure_fn = load("next_departure")
    departure_results = []
    for row in rows:
        if (row["task"], row["channel"]) != ("next_departure", "code"):
            continue
        terms = translate(departure_case, departure_gold, row["candidate"])
        bus, earliest, ret = (terms.scope[key] for key in ("bus_id", "min_time", "ret"))
        # This source-level expression matches Python % for exactly bus > 0.
        remainder = earliest % bus
        program = z3.If(remainder == 0, earliest, earliest - remainder + bus)
        departure_results.append({
            "slot_id": row["slot_id"],
            "candidate_rejects_program_result_on_positive_bus": query(z3.And(
                bus > 0, terms.candidate_pre, ret == program, z3.Not(terms.candidate_post),
            )),
            "candidate_allows_alternative_result_on_positive_bus": query(z3.And(
                bus > 0, terms.candidate_pre, terms.candidate_post, ret != program,
            )),
        })

    return {
        "parse_input": {
            "native_self_check": native_outcome(parse_case, parse_gold, parse_gold),
            "typed_tuple_self_check": audit(parse_terms),
            "typed_tuple_wrong_width_control": {
                "input": [".."], "result": [2, 1, ".."],
                "counterexample_query": query(z3.And(
                    wrong_width.gold_pre, wrong_width.gold_post,
                    z3.Not(wrong_width.candidate_post),
                    wrong_width.scope["lines"] == z3.Unit(z3.StringVal("..")),
                    wrong_width.scope["ret"] == wrong_width.scope["ret"].sort().constructor(0)(
                        2, 1, z3.StringVal(".."),
                    ),
                )),
            },
            "python_pairs": parse_rows,
        },
        "csv_first_column": {
            "input": csv_source, "python_result": csv_fn(csv_source),
            "incorrect_result_for_post_witness": ["x"],
            "archived_unknowns": csv_results, "universal_code_domain": csv_dead_domain,
        },
        "average": {
            "input": [0.0, 2.0], "python_result": average_fn([0.0, 2.0]),
            "incorrect_result_under_test": 0, "gold_allows_incorrect_result": (
                average_underspecification
            ),
        },
        "extract_expression": {
            "input": expression, "python_exception": expression_exception,
            "gold_pre_counterexample": query(z3.And(
                expression_terms.scope["expr"] == expression, z3.Not(expression_terms.gold_pre),
            )),
            "unsound_refinement": {
                "slot_id": expression_row["slot_id"], "candidate": expression_row["candidate"],
                "input": exact_substring_input, "python_result": exact_substring_output,
                "gold_admits_and_candidate_rejects_actual": refinements_against_code,
            },
        },
        "solve": {
            "input": [solve_input, preamble], "python_result": solve_fn(solve_input, preamble),
            "gold_intended_position_pairs": position_pairs, "gold_intended_result": None,
        },
        "duration": {
            "input": [2, 1], "python_result": duration_fn(2, 1),
            "gold_rejects_input": query(z3.And(duration_binding, z3.Not(duration_terms.gold_pre))),
            "candidate_admits_result": query(z3.And(
                duration_binding, duration_terms.candidate_pre, duration_terms.candidate_post,
            )),
            "candidate_post_disagrees_with_program": query(z3.Xor(
                duration_terms.candidate_post, duration_terms.scope["ret"] == end - start + 1,
            )),
        },
        "next_departure": {
            "input_outside_gold": [3, -1], "python_result": departure_fn(3, -1),
            "checks_over_candidate_domain_with_positive_bus": departure_results,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    records, finals, scores = load_dev()
    synthetic = controls()
    by_name = {row["case"]: row for row in synthetic}
    assert by_name["discarded_pre_conjunction"]["native"]["equivalent"]
    assert by_name["discarded_pre_conjunction"]["independent"]["direct_equivalence"] == "refuted"
    assert by_name["vocabulary_heuristic"]["native"]["reason"] == "vacuous_equivalence"
    assert by_name["vocabulary_heuristic"]["independent"]["nonvacuous_equivalence"] == "proved"
    assert by_name["stronger_post"]["independent"]["nonvacuous_refinement"] == "proved"
    assert by_name["weaker_post"]["independent"]["nonvacuous_refinement"] == "refuted"
    assert by_name["feasible_for_some_inputs_only"]["independent"][
        "candidate_non_vacuity"
    ] == "refuted"
    assert by_name["tautology"]["independent"]["nonvacuous_equivalence"] == "refuted"
    assert by_name["contradiction"]["independent"]["nonvacuous_equivalence"] == "refuted"
    rows = audit_saved(records, finals, scores)
    witnesses = dev_gold_witnesses(records, rows)
    assert witnesses["parse_input"]["typed_tuple_self_check"]["direct_equivalence"] == "proved"
    wrong_width = witnesses["parse_input"]["typed_tuple_wrong_width_control"]
    assert wrong_width["counterexample_query"]["status"] == "sat"
    csv_witnesses = witnesses["csv_first_column"]["archived_unknowns"]
    assert all(row["query"]["status"] == "sat" for row in csv_witnesses)
    assert witnesses["csv_first_column"]["universal_code_domain"]["result"]["status"] == "unsat"
    unsound_refinement = witnesses["extract_expression"]["unsound_refinement"]
    assert unsound_refinement["gold_admits_and_candidate_rejects_actual"]["status"] == "sat"
    report = {
        "inputs": {
            "archive": str(ARCHIVE.relative_to(ROOT)),
            "archive_sha256": hashlib.sha256(ARCHIVE.read_bytes()).hexdigest(),
            "dev_tasks": len(records), "candidate_slots": len(rows),
            "z3": z3.get_full_version(), "default_timeout_ms": TIMEOUT_MS,
        },
        "summary": {
            "historical": dict(Counter(row["historical_status"] for row in rows)),
            **{
                metric: dict(Counter(row["direct_same_translation"].get(metric, "parse_error")
                                     for row in rows))
                for metric in (
                    "direct_equivalence", "nonvacuous_equivalence",
                    "nonvacuous_refinement", "candidate_non_vacuity",
                )
            },
            "mixed_tuple_ablation": dict(Counter(
                row["direct_typed_tuple"]["direct_equivalence"]
                for row in rows if "direct_typed_tuple" in row
            )),
        },
        "controlled_pairs": synthetic, "python_translation": model_mismatches(),
        "solver_limits": timeout_control(), "dev_witnesses": witnesses, "dev_results": rows,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
