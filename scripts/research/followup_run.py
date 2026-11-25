"""Separate numeric DSL guidance from witnesses, and test judge on archived unknowns."""

import argparse
import json
import time
from pathlib import Path

from contract_cases import CASES
from groq_runs import OSS, QWEN, Groq
from pipeline_audit import _load_cases, _read_archive

ROUNDING = "In the formula language integer division uses SMT rounding."
CSV_SLOTS = ("spec:treatment:1", "code:treatment:1")


def csv_judge(client: Groq) -> None:
    manifest, records, _, _ = _read_archive(Path.cwd())
    cases = _load_cases(Path.cwd(), manifest)
    for slot in CSV_SLOTS:
        channel = slot.split(":")[0]
        row = next(
            r for key, r in records.items() if key.endswith(f"::csv_first_column:{slot}")
        )
        extraction = row["extraction"]
        case = cases[extraction["benchmark_id"]]
        source = case.informal_spec if channel == "spec" else case.function_source
        contract = {
            key: extraction[key] for key in ("domain_constraints", "postcondition")
        }
        prompt = (
            "Check whether this candidate exactly characterizes the result and domain of the "
            "source. Use list-of-string semantics and conjoin all preconditions. The "
            "verification system returned unknown. If you can disprove the candidate, propose "
            "a counterexample with a single input row containing a comma. Return JSON with "
            "verdict PASS, FAIL or UNKNOWN, and a witness null or an object with the keys "
            "lines (list of one string), kind (rejects_input, rejects_return, "
            "or admits_wrong_return), ret (list of strings for return witnesses, null otherwise). "
            "Provide a concrete input and an explicit return whenever needed.\n"
            f"Signature: {case.signature}\nSource: {source}\nCandidate: {json.dumps(contract)}"
        )
        for name, model in (("qwen", QWEN), ("oss", OSS)):
            client.call(f"fallback-csv-{channel}-{name}", model, prompt, 0)


def numeric_factorial(client: Groq) -> None:
    pending = [(case, channel) for case in CASES
               if case.name in {"signed_bucket", "signed_remainder"}
               for channel in ("spec", "code")]
    while pending:
        ready = []
        for case, channel in pending:
            prefix = f"{case.name}-{channel}"
            path = client.output / f"gen-{prefix}-witness.json"
            if not path.exists():
                continue
            saved = json.loads(path.read_text())["request"]["messages"]
            if not saved[-1]["content"].endswith(ROUNDING):
                ready.append((case, channel))
                continue
            history = tuple(saved[:-1])
            prompt, _, _ = saved[-1]["content"].rpartition(" " + ROUNDING)
            without_witness = prompt.split("\nThe following counterexample", 1)[0]
            outcomes = (
                ("rounding", without_witness + "\n" + ROUNDING), ("example", prompt),
            )
            if channel == "code":
                outcomes = outcomes[::-1]
            for name, question in outcomes:
                client.call(f"factor-{prefix}-{name}", QWEN, question, 0.7, history)
            ready.append((case, channel))
        pending = [pair for pair in pending if pair not in ready]
        if pending and not ready:
            time.sleep(5)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--env", type=Path)
    args = parser.parse_args()
    client = Groq(args.output, args.env)
    client.preflight({QWEN, OSS})
    csv_judge(client)
    numeric_factorial(client)


if __name__ == "__main__":
    main()
