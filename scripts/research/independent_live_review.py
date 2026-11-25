"""Check saved research trials against execution on a disjoint input grid."""

import argparse
import hashlib
import itertools
import json
from collections import Counter
from dataclasses import asdict
from pathlib import Path

import z3
from contract_cases import CASES, Case
from followup_run import ROUNDING
from groq_runs import content, payload
from live_analysis import label, parse, python_function, read, verified_witness
from pipeline_audit import ArchiveReplay, Exchange, Variant, validation_variant

from dualify.phases.p01_spec_to_logic import extract_spec_logic
from dualify.phases.p02_code_to_logic import extract_code_logic

EDGE_VALUES = (-(2**55), -223, -17, -9, 9, 17, 223, 2**55)
ARMS = ("initial", "fresh", "revision", "witness", "baseline", "both")


def execute(case: Case, raw: dict) -> dict:
    contract = parse(case, raw)
    function = python_function(case)
    known = {args for args, _ in case.examples}
    counters: Counter[str] = Counter()
    first_failure = None
    # Every coordinate is outside the [-4, 4] execution grid exposed during code repair.
    for args in itertools.product(EDGE_VALUES, repeat=len(contract.vars)):
        if args in known:
            continue
        counters["inputs"] += 1
        try:
            actual = function(*args)
        except ValueError:
            actual = None
        pre = contract.at(contract.pre, args)
        problem = None
        wrong_return = None
        wrong_return_verdict = None
        if not z3.eq(pre, z3.BoolVal(actual is not None)):
            problem = "wrong_domain"
        elif actual is not None:
            post = contract.at(contract.post, args)

            def admits(value: int | bool, formula: z3.BoolRef = post) -> z3.BoolRef:
                return z3.simplify(z3.substitute(formula, (contract.ret, contract.value(value))))

            counters["actual_returns"] += 1
            if not z3.is_true(admits(actual)):
                problem = "actual_return_not_proved"
            alternatives: set[int | bool]
            alternatives = {not actual} if type(actual) is bool else {actual - 1, actual + 1, 0}
            for alternative in sorted(alternatives - {actual}):
                counters["wrong_returns"] += 1
                alternative_verdict = admits(alternative)
                if not z3.is_false(alternative_verdict):
                    problem = "wrong_return_not_excluded"
                    wrong_return = alternative
                    wrong_return_verdict = str(alternative_verdict)
        if problem:
            counters[problem] += 1
            if first_failure is None:
                first_failure = {
                    "args": args,
                    "python_return": actual,
                    "candidate_precondition": str(pre),
                    "alternative_return": wrong_return,
                    "alternative_return_verdict": wrong_return_verdict,
                    "reason": problem,
                }
    return {"counts": dict(counters), "first_failure": first_failure}


def feedback(
    case: Case, initial: dict, revision: dict, witness: dict,
) -> str:
    before = revision["request"]["messages"]
    after = witness["request"]["messages"]
    assert before[:-1] == after[:-1]
    assert before[-2]["content"] == (content(initial["response"]) or "{}")
    if before == after:
        return "identical_to_revision"
    text = after[-1]["content"]
    marker = "The following counterexample is verified"
    if marker in text:
        start = text.index("{", text.index(marker))
        proposal, _ = json.JSONDecoder().raw_decode(text[start:])
        assert verified_witness(case, payload(initial["response"]), proposal)
        return "concrete_witness_verified"
    assert "The typed formula check rejected the proposal:" in text
    return "typed_error"


def replay_native(root: Path, case: Case, channel: str, variant: Variant, row: dict) -> int:
    prefix = f"{case.name}-{channel}"
    first, *repairs = row["calls"]
    assert first == f"gen-{prefix}-initial"
    initial = read(root, first)
    assert initial is not None
    exchanges: list[Exchange] = [
        (initial["request"]["messages"][-1]["content"], payload(initial["response"])),
    ]
    for slot in repairs:
        recorded = read(root, slot)
        assert recorded is not None
        prompt = recorded["request"]["messages"][-1]["content"]
        digest = hashlib.sha256(prompt.encode()).hexdigest()[:16]
        assert slot == f"repair-{prefix}-{digest}"
        assert recorded["request"]["temperature"] == 0
        exchanges.append((prompt, payload(recorded["response"])))
    client = ArchiveReplay(exchanges)
    extractor = extract_spec_logic if channel == "spec" else extract_code_logic
    with validation_variant(variant):
        extraction = extractor(
            client, f"research::{case.name}", case.signature,
            case.prose if channel == "spec" else case.source,
            case.return_type, arg_types=dict.fromkeys(case.args.split(), "int"),
        )
    assert client.censored is None and client.matched_calls == len(exchanges)
    assert asdict(extraction) == row["extraction"]
    return len(exchanges)


def review(root: Path) -> dict:
    availability: Counter[str] = Counter()
    feedback_modes: Counter[str] = Counter()
    exact_checks = {}
    native_pairs = {}
    second_arm_pairs = {}
    numeric_factors = {}
    for case, channel in itertools.product(CASES, ("spec", "code")):
        prefix = f"{case.name}-{channel}"
        records = {arm: read(root, f"gen-{prefix}-{arm}") for arm in ARMS[:4]}
        native = {arm: read(root, f"native-{prefix}-{arm}") for arm in ARMS[4:]}
        initial, fresh = records["initial"], records["fresh"]
        if initial and fresh:
            assert initial["request"] == fresh["request"]
            initial_id = initial["response"].get("id")
            assert initial_id is None or initial_id != fresh["response"].get("id")
        revision, witness = records["revision"], records["witness"]
        if initial and revision and witness:
            mode = feedback(case, initial, revision, witness)
            feedback_modes[f"{channel}:{mode}"] += 1
        else:
            mode = None
        labels = {}
        exact_native_calls = {}
        for arm, trial in {**records, **native}.items():
            if trial is None:
                continue
            availability[arm] += 1
            raw = trial["extraction"] if arm in native else payload(trial["response"])
            verdict = label(case, raw)["verdict"]
            labels[arm] = verdict
            if arm in native:
                variant: Variant = "baseline" if arm == "baseline" else "both"
                exact_native_calls[arm] = replay_native(root, case, channel, variant, trial)
            if verdict == "exact":
                exact_checks[f"{prefix}:{arm}"] = execute(case, raw)
        if "baseline" in labels and "both" in labels:
            baseline, corrected = native["baseline"], native["both"]
            assert baseline is not None and corrected is not None
            trace = baseline["extraction"].get("extraction_trace") or {}
            native_pairs[prefix] = {
                "baseline": labels["baseline"],
                "corrected": labels["both"],
                "baseline_calls": exact_native_calls["baseline"],
                "corrected_calls": exact_native_calls["both"],
                "baseline_initial_errors": trace.get("initial", {}).get("errors"),
                "corrected_postcondition": corrected["extraction"]["postcondition"],
                "corrected_preconditions": corrected["extraction"]["domain_constraints"],
                "code_witness_against_baseline": (
                    execute(case, baseline["extraction"])["first_failure"]
                    if labels["baseline"] == "different" and labels["both"] == "exact"
                    else None
                ),
            }
        if mode is not None and "fresh" in labels:
            second_arm_pairs[prefix] = {
                "feedback": mode,
                **{arm: labels[arm] for arm in ("fresh", "revision", "witness")},
            }
        for arm in ("rounding", "example"):
            stored = read(root, f"factor-{prefix}-{arm}")
            if stored is None:
                continue
            assert revision is not None and witness is not None
            messages = stored["request"]["messages"]
            assert messages[:-1] == witness["request"]["messages"][:-1]
            if arm == "rounding":
                assert messages[-1]["content"] == revision["request"]["messages"][-1]["content"] + (
                    "\n" + ROUNDING
                )
            else:
                augmented = witness["request"]["messages"][-1]["content"]
                assert augmented == messages[-1]["content"] + " " + ROUNDING
            raw = payload(stored["response"])
            verdict = label(case, raw)["verdict"]
            numeric_factors[f"{prefix}:{arm}"] = verdict
            if verdict == "exact":
                exact_checks[f"{prefix}:{arm}"] = execute(case, raw)
    solved = [
        json.loads(path.read_text()) for path in sorted(root.glob("*.json"))
        if path.name.startswith((
            "gen-", "repair-", "judge-", "origin-", "provenance-", "context-",
            "factor-", "fallback-",
        ))
    ]
    ids = [row["response"]["id"] for row in solved if "id" in row["response"]]
    assert len(ids) == len(set(ids))
    return {
        "independence": (
            "Candidate terms and verdicts use the study's typed parser. Ground truth for "
            "the additional checks is actual execution of the public new scalar fixtures. "
            "This finite grid excludes repair feedback inputs and authored sample inputs."
        ),
        "independent_grid_values": EDGE_VALUES,
        "availability": dict(availability),
        "native_pairs": native_pairs,
        "second_arm_pairs": second_arm_pairs,
        "numeric_factors": numeric_factors,
        "feedback_modes": dict(feedback_modes),
        "exact_candidate_execution": exact_checks,
        "transport": {
            "logical_records": len(solved),
            "physical_posts_in_saved_records": sum(len(row["posts"]) for row in solved),
            "unique_completions": len(ids),
            "model_fingerprints": {
                model: len({
                    row["response"].get("system_fingerprint") for row in solved
                    if row["response"].get("model") == model
                })
                for model in {row["response"]["model"] for row in solved if "id" in row["response"]}
            },
        },
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    result = review(args.input)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
