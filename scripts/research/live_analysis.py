"""Score the saved live trials without any API calls or historical held-out files."""

import argparse
import ast
import itertools
import json
import random
from collections import Counter
from functools import cache
from pathlib import Path
from typing import Any

import z3
from contract_cases import CASES, Case
from followup_run import CSV_SLOTS
from generation_run import arg_types, revision_prompt
from groq_runs import payload
from judge_cases import PAIRS, describe
from oracle_audit import query as audit_query
from oracle_audit import sequence, translate, unfold_csv_at_length_one
from pipeline_audit import _load_cases, _read_archive

from dualify.formula_parser import extract_quantifier_binders, validate_formula
from dualify.gold_scoring import GoldContract, score_extraction_against_gold
from dualify.phases.p01_spec_to_logic import _ALLOWED_CALLS
from dualify.phases.p03_smt_checking import CaseSpec, _canonicalize_expression
from dualify.research_codegen import UnsupportedSource, compile_contract
from dualify.research_contracts import Contract, FormulaError, relation
from dualify.types import ExtractionResult


@cache
def python_function(case: Case) -> Any:
    namespace: dict[str, Any] = {}
    exec(case.source, namespace)
    return namespace[case.name]


def python_return(case: Case, inputs: tuple[int, ...]) -> int | bool | None:
    try:
        return python_function(case)(*inputs)
    except ValueError:
        return None


def parse(case: Case, raw: dict) -> Contract:
    return Contract(
        arg_types(case), case.return_type, raw.get("domain_constraints"), raw.get("postcondition"),
    )


def reference(case: Case) -> Contract:
    return Contract(arg_types(case), case.return_type, [case.pre], case.post)


def label(case: Case, raw: dict) -> dict:
    try:
        candidate = parse(case, raw)
    except FormulaError as error:
        return {"verdict": "invalid", "reason": str(error)}
    pre, post = relation(candidate, reference(case))
    verdict = "exact" if (pre, post) == ("unsat", "unsat") else (
        "different" if "sat" in (pre, post) else "unknown"
    )
    return {"verdict": verdict, "pre_xor": pre, "post_xor": post}


def historical_payload(case: Case, raw: dict) -> dict:
    pre, post = raw.get("domain_constraints"), raw.get("postcondition")
    if not isinstance(pre, list) or not all(isinstance(x, str) for x in [*pre, post]):
        return {"reason": "malformed_payload"}
    # The production evaluator uses eval. Keep live strings inside its safe formula grammar.
    allowed = _ALLOWED_CALLS | {"String", "Char", "IntVal", "RealVal", "BoolVal"}
    for formula in (*pre, post):
        canonical = _canonicalize_expression(formula, f"research::{case.name}")
        names = set(arg_types(case)) | {"ret"} | extract_quantifier_binders(canonical)
        if validate_formula(canonical, names):
            return {"reason": "outside_historical_research_grammar"}
        if any(
            isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
            and node.func.id not in allowed
            for node in ast.walk(ast.parse(canonical, mode="eval"))
        ):
            return {"reason": "outside_historical_research_grammar"}
    return historical(case, raw)


def historical(case: Case, raw: dict) -> dict:
    # Use exactly the same unmodified gold scorer for all experimental arms.
    types = arg_types(case)
    bid = f"research::{case.name}"
    spec = CaseSpec(bid, types, case.return_type)
    gold = GoldContract(bid, case.name, True, list(types), types, case.return_type,
                        [case.pre], case.post)
    extraction = ExtractionResult(
        bid, list(types), case.return_type, raw["domain_constraints"],
        raw["postcondition"], "", "",
    )
    result = score_extraction_against_gold(case_spec=spec, gold=gold, extraction=extraction)
    return {"equivalent": result.contract_equivalent, "reason": result.reason}


def dynamic(case: Case, candidate: Contract, channel: str | None = None) -> dict:
    test_values = (-17, -5, -2, -1, 0, 1, 2, 5, 17)
    inputs = set(itertools.product(test_values, repeat=len(candidate.vars)))
    inputs.update(args for args, _ in case.examples)
    counts: Counter[str] = Counter()
    unseen: Counter[str] = Counter()
    authored_inputs = {args for args, _ in case.examples}
    for args in sorted(inputs):
        sample: Counter[str] = Counter()
        actual = python_return(case, args)
        pre = candidate.at(candidate.pre, args)
        sample["inputs"] += 1
        if z3.is_true(pre) != (actual is not None) or not (
            z3.is_true(pre) or z3.is_false(pre)
        ):
            sample["domain_disagreements"] += 1
        if actual is not None:
            sample["valid_inputs"] += 1
            post = candidate.at(candidate.post, args)
            truth = candidate.value(actual)
            if not z3.is_true(z3.simplify(z3.substitute(post, (candidate.ret, truth)))):
                sample["actual_return_disagreements"] += 1
            alternatives = {not actual} if type(actual) is bool else {actual + 1, actual - 1, 0}
            for alternative in alternatives - {actual}:
                wrong = candidate.value(alternative)
                sample["wrong_returns"] += 1
                if not z3.is_false(z3.simplify(z3.substitute(post, (candidate.ret, wrong)))):
                    sample["wrong_return_not_rejected"] += 1
        counts.update(sample)
        if channel == "spec" and args not in authored_inputs or (
            channel == "code" and any(abs(value) > 4 for value in args)
        ):
            unseen.update(sample)
    return {**counts, **({"out_of_feedback": dict(unseen)} if channel else {})}


def evaluate(case: Case, raw: dict, channel: str | None = None) -> dict:
    result = {**label(case, raw), "historical": historical_payload(case, raw)}
    if result["verdict"] != "invalid":
        result["execution"] = dynamic(case, parse(case, raw), channel)
    return result


def read(output: Path, key: str) -> dict | None:
    path = output / f"{key}.json"
    return json.loads(path.read_text()) if path.exists() else None


def measure_generation(output: Path) -> list[dict]:
    rows = []
    for case, channel in itertools.product(CASES, ("spec", "code")):
        prefix = f"{case.name}-{channel}"
        for arm in ("initial", "fresh", "revision", "witness", "baseline", "both"):
            native = arm in {"baseline", "both"}
            key = f"native-{prefix}-{arm}" if native else f"gen-{prefix}-{arm}"
            stored = read(output, key)
            if stored is None:
                continue
            result = stored["extraction"] if native else payload(stored["response"])
            row = {
                "case": case.name, "channel": channel, "arm": arm,
                **evaluate(case, result, channel),
                "declared_signature_matches": (
                    result.get("args") == list(arg_types(case))
                    and result.get("return_type") == case.return_type
                ),
            }
            if native:
                row.update(calls=stored["calls"], degraded=result["degraded"])
            if arm == "witness":
                initial = read(output, f"gen-{prefix}-initial")
                if initial is not None:
                    _, control = revision_prompt(case, channel, initial["response"], feedback=False)
                    prompt = stored["request"]["messages"][-1]["content"]
                    row["feedback"] = (
                        "witness" if "counterexample is verified" in prompt else
                        "type_error" if prompt != control else "none"
                    )
            rows.append(row)
    return rows


def measure_compiler() -> dict:
    results = {}
    for variant, python_division in (("python", True), ("raw_smt", False)):
        rows = []
        for case in CASES:
            entry = {"case": case.name, "channel": "code", "model_calls": 0}
            try:
                contract = compile_contract(case.source, python_division=python_division)
            except UnsupportedSource as exc:
                rows.append({**entry, "verdict": "abstained", "reason": str(exc)})
            else:
                rows.append({**entry, "payload": contract, **evaluate(case, dict(contract))})
        execution: Counter[str] = Counter()
        for row in rows:
            execution.update(row.get("execution", {}))
        results[variant] = {
            "coverage": {"cases": len(rows), "compiled": sum("payload" in row for row in rows)},
            "typed": dict(Counter(row["verdict"] for row in rows)),
            "historical_equivalent": sum(row.get("historical", {}).get("equivalent", False)
                                         for row in rows),
            "execution": dict(execution), "cases": rows,
        }
    return results


def measure_dev_compiler_coverage() -> list[dict]:
    root = Path.cwd()
    manifest, _, _, _ = _read_archive(root)
    rows = []
    for case in _load_cases(root, manifest).values():
        try:
            contract = compile_contract(case.function_source)
        except UnsupportedSource as exc:
            rows.append({"task": case.qualname, "eligible": False, "reason": str(exc)})
        else:
            rows.append({"task": case.qualname, "eligible": True, "payload": contract})
    return rows


def verified_witness(case: Case, raw: dict, witness: dict) -> bool:
    try:
        proposal = witness["args"]
        if set(proposal) != set(arg_types(case)) or any(
            type(value) is not int for value in proposal.values()
        ):
            return False
        inputs = tuple(proposal[name] for name in arg_types(case))
        actual = python_return(case, inputs)
        candidate = parse(case, raw)
        pre = candidate.at(candidate.pre, inputs)
        kind = witness["kind"]
        if kind == "rejects_input":
            return actual is not None and z3.is_false(pre)
        if kind == "accepts_input":
            return actual is None and z3.is_true(pre)
        if actual is None or not z3.is_true(pre):
            return False
        post = candidate.at(candidate.post, inputs)
        returned = witness["ret"]
        term = candidate.value(returned)
        truth = z3.simplify(z3.substitute(post, (candidate.ret, term)))
        if kind == "rejects_return":
            return returned == actual and z3.is_false(truth)
        return kind == "admits_wrong_return" and returned != actual and z3.is_true(truth)
    except (FormulaError, KeyError, TypeError, AttributeError):
        return False


def measure_judges(output: Path) -> list[dict]:
    rows = []
    for index, correct, incorrect, defect in PAIRS:
        case = CASES[index]
        for variant, family in itertools.product(
            ("base", "swapped", "repeated", "style", "neutral_style", "cross_source"),
            ("qwen", "oss"),
        ):
            stored = read(output, f"judge-{index}-{variant}-{family}")
            if stored is None:
                continue
            correct_first = (index % 2 == 0) != (variant == "swapped")
            positive, negative = ("A", "B") if correct_first else ("B", "A")
            result = payload(stored["response"])
            witness = result.get("witness")
            validated = False
            if isinstance(witness, dict) and witness.get("candidate") in (positive, negative):
                target = correct if witness["candidate"] == positive else incorrect
                validated = verified_witness(case, describe(target), witness)
            rows.append({
                "case": case.name, "defect": defect, "variant": variant, "judge": family,
                "positive": result.get(positive), "negative": result.get(negative),
                "correct_rank": result.get("prefer") == positive,
                "correct_first": correct_first, "prefer": result.get("prefer"),
                "proposed_witness": isinstance(witness, dict), "verified_witness": validated,
            })
    return rows


def measure_origin(output: Path) -> tuple[list[dict], list[dict]]:
    cross, context = [], []
    for index, case in enumerate(CASES):
        qwen = read(output, f"gen-{case.name}-spec-initial")
        oss = read(output, f"origin-{index}-oss")
        if qwen is not None:
            exact = label(case, payload(qwen["response"]))
            for variant in ("fresh", "same"):
                stored = read(output, f"context-{index}-{variant}")
                if stored is not None:
                    context.append({
                        "case": case.name, "variant": variant, "label": exact["verdict"],
                        "verdict": payload(stored["response"]).get("verdict"),
                    })
        if qwen is None or oss is None:
            continue
        qwen_label = label(case, payload(qwen["response"]))["verdict"]
        oss_label = label(case, payload(oss["response"]))["verdict"]
        for order, judge in itertools.product(range(2), ("qwen", "oss")):
            stored = read(output, f"provenance-{index}-{order}-{judge}")
            if stored is None:
                continue
            response = payload(stored["response"])
            a, b = ("qwen", "oss") if order == 0 else ("oss", "qwen")
            preference = response.get("prefer")
            cross.append({
                "case": case.name, "order": order, "judge": judge,
                "qwen_label": qwen_label, "oss_label": oss_label,
                "qwen_verdict": response.get("A" if a == "qwen" else "B"),
                "oss_verdict": response.get("A" if a == "oss" else "B"),
                "preference": a if preference == "A" else b if preference == "B" else preference,
            })
    return cross, context


def measure_followup(output: Path) -> dict:
    arm_rows = []
    for case, channel, arm in itertools.product(
        CASES, ("spec", "code"), ("rounding", "example"),
    ):
        stored = read(output, f"factor-{case.name}-{channel}-{arm}")
        if stored is not None:
            arm_rows.append({
                "case": case.name, "channel": channel, "arm": arm,
                **evaluate(case, payload(stored["response"]), channel),
            })
    root = Path.cwd()
    manifest, records, _, _ = _read_archive(root)
    dev = _load_cases(root, manifest)
    csv_rows = []
    for slot in CSV_SLOTS:
        channel = slot.split(":")[0]
        row = next(r for key, r in records.items() if key.endswith(f"::csv_first_column:{slot}"))
        extraction = row["extraction"]
        case = dev[extraction["benchmark_id"]]
        formula = extraction["domain_constraints"], extraction["postcondition"]
        case_spec = CaseSpec(case.benchmark_id, case.arg_types, case.return_type)
        terms = translate(case_spec, formula, formula)
        lines, ret = terms.scope["lines"], terms.scope["ret"]
        namespace: dict = {}
        exec("from __future__ import annotations\n" + case.function_source, namespace)
        for family in ("qwen", "oss"):
            saved = read(output, f"fallback-csv-{channel}-{family}")
            if saved is None:
                continue
            data = payload(saved["response"])
            witness = data.get("witness")
            valid = False
            check: dict = {}
            if isinstance(witness, dict):
                inputs, result = witness.get("lines"), witness.get("ret")
                if isinstance(inputs, list) and len(inputs) == 1 and (
                    isinstance(inputs[0], str) and "," in inputs[0]
                ):
                    actual = namespace["csv_first_column"](inputs)
                    pre = unfold_csv_at_length_one(z3.substitute(
                        terms.candidate_pre, (lines, sequence(inputs, lines.sort())),
                    ), [])
                    check["pre"] = audit_query(pre)
                    if witness.get("kind") == "rejects_input":
                        valid = check["pre"]["status"] == "unsat"
                    elif isinstance(result, list) and all(isinstance(x, str) for x in result):
                        post = z3.substitute(
                            terms.candidate_post, (lines, sequence(inputs, lines.sort())),
                            (ret, sequence(result, ret.sort())),
                        )
                        check["not_pre"] = audit_query(z3.Not(pre))
                        check["post"] = audit_query(post)
                        check["not_post"] = audit_query(z3.Not(post))
                        if check["not_pre"]["status"] == "unsat":
                            valid = (
                                witness.get("kind") == "rejects_return" and result == actual
                                and check["post"]["status"] == "unsat"
                            ) or (
                                witness.get("kind") == "admits_wrong_return" and result != actual
                                and check["not_post"]["status"] == "unsat"
                            )
            csv_rows.append({
                "slot": slot, "judge": family, "verdict": data.get("verdict"),
                "witness": witness, "verified": valid, "checks": check,
            })
    return {"signed_factorial": arm_rows, "csv_unknown": csv_rows}


def paired_interval(left: list[bool], right: list[bool]) -> list[float] | None:
    deltas = [int(b) - int(a) for a, b in zip(left, right, strict=True)]
    if not deltas:
        return None
    rng = random.Random(20261125)
    estimates = sorted(
        sum(rng.choices(deltas, k=len(deltas))) / len(deltas) for _ in range(10_000)
    )
    return [estimates[250], estimates[9749]]


def summarize_generation(rows: list[dict]) -> dict:
    result = {}
    for channel in ("spec", "code"):
        grouped = {arm: {r["case"]: r for r in rows
                        if r["arm"] == arm and r["channel"] == channel}
                   for arm in ("initial", "fresh", "revision", "witness", "baseline", "both")}
        table = {arm: {
            "n": len(items), "planned": len(CASES),
            "exact": sum(r["verdict"] == "exact" for r in items.values()),
            "invalid": sum(r["verdict"] == "invalid" for r in items.values()),
            "unknown": sum(r["verdict"] == "unknown" for r in items.values()),
            "historical": sum(r["historical"].get("equivalent", False)
                              for r in items.values()),
            "historical_scored": sum("equivalent" in r["historical"] for r in items.values()),
            "declared_signature_matches": sum(
                r["declared_signature_matches"] for r in items.values()
            ),
        } for arm, items in grouped.items()}
        for arm in ("fresh", "revision", "witness"):
            overlap = grouped["initial"].keys() & grouped[arm].keys()
            table[arm]["initial_or_second_exact"] = sum(
                any(grouped[key][name]["verdict"] == "exact" for key in ("initial", arm))
                for name in overlap
            )
        for arm in ("fresh", "revision", "baseline"):
            target = "both" if arm == "baseline" else "witness"
            paired = sorted(grouped[arm].keys() & grouped[target].keys())
            table[target][f"delta_vs_{arm}_95pct"] = paired_interval(
                [grouped[arm][name]["verdict"] == "exact" for name in paired],
                [grouped[target][name]["verdict"] == "exact" for name in paired],
            )
        result[channel] = table
    return result


def summarize_judges(rows: list[dict]) -> dict:
    return {family: {variant: {
        "n": len(group),
        "false_accept": sum(row["negative"] == "PASS" for row in group),
        "false_reject": sum(row["positive"] == "FAIL" for row in group),
        "abstained": sum(row[sign] not in {"PASS", "FAIL"} for row in group
                         for sign in ("positive", "negative")),
        "correct_rank": sum(row["correct_rank"] for row in group),
        "proposed_witness": sum(row["proposed_witness"] for row in group),
        "verified_witness": sum(row["verified_witness"] for row in group),
    } for variant in ("base", "swapped", "repeated", "style", "neutral_style", "cross_source")
      if (group := [r for r in rows if r["variant"] == variant and r["judge"] == family])}
        for family in ("qwen", "oss")}


def cost(output: Path) -> dict:
    groups: dict[str, Counter[str]] = {}
    arms: dict[str, Counter[str]] = {}
    fingerprints: Counter[str] = Counter()
    ids = []
    for path in sorted(output.glob("*.json")):
        data = json.loads(path.read_text())
        if "request" not in data:
            continue
        group = path.name.split("-", 1)[0]
        totals = groups.setdefault(group, Counter())
        totals["logical_calls"] += 1
        totals["posts"] += len(data["posts"])
        totals["seconds_http"] += sum(p["seconds"] for p in data["posts"])
        for post in data["posts"]:
            totals[f"http_{post['status']}"] += 1
        response = data["response"]
        if "id" in response:
            ids.append(response["id"])
            if response["model"] != data["request"]["model"]:
                raise ValueError(f"Unexpected model at {path.name}")
            fingerprints[f"{response['model']}:{response.get('system_fingerprint')}"] += 1
        arm = arms.setdefault(path.stem.rsplit("-", 1)[-1], Counter()) if group == "gen" else None
        for key in ("prompt_tokens", "completion_tokens"):
            used = response.get("usage", {}).get(key, 0)
            totals[key] += used
            if arm is not None:
                arm[key] += used
    return {
        "by_stage": {group: dict(totals) for group, totals in groups.items()},
        "generation_arm_tokens": {arm: dict(totals) for arm, totals in arms.items()},
        "fingerprints_by_model": dict(fingerprints),
        "completion_ids": len(ids), "unique_completion_ids": len(set(ids)),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    fixture_checks = {}
    for case in CASES:
        assert all(python_return(case, arg) == expected for arg, expected in case.examples)
        fixture_checks[case.name] = dynamic(case, reference(case))
        assert not any(
            "disagreement" in key or "not_rejected" in key for key in fixture_checks[case.name]
        )
    for index, correct, incorrect, _ in PAIRS:
        case = CASES[index]
        assert label(case, describe(correct))["verdict"] == "exact"
        assert label(case, describe(incorrect))["verdict"] == "different"
    rows = measure_generation(args.input)
    judge = measure_judges(args.input)
    origin, context = measure_origin(args.input)
    args.output.write_text(json.dumps({
        "fixture_checks": fixture_checks,
        "generation_summary": summarize_generation(rows),
        "generation": rows,
        "followup": measure_followup(args.input),
        "source_compiler": measure_compiler(),
        "dev_compiler_coverage": measure_dev_compiler_coverage(),
        "judge_summary": summarize_judges(judge),
        "judge": judge, "crossed_provenance": origin, "same_context": context,
        "cost": cost(args.input), "z3": z3.get_version_string(),
    }, indent=2) + "\n")


if __name__ == "__main__":
    main()
