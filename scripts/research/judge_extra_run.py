"""Pointwise self-context checks and crossed judge/candidate provenance."""

import argparse
import json
import time
from pathlib import Path

from contract_cases import CASES
from generation_run import native_prompt
from groq_runs import OSS, QWEN, Groq, content, payload
from judge_cases import PAIRS, describe, source_for
from judge_run import make_prompt


def formulas(raw: dict) -> dict:
    return {
        "domain_constraints": raw.get("domain_constraints"),
        "postcondition": raw.get("postcondition"),
    }


def run(client: Groq) -> None:
    for index, correct, incorrect, _ in PAIRS:
        a, b = map(describe, (correct, incorrect) if index % 2 == 0 else (incorrect, correct))
        target = b if index % 2 == 0 else a
        target["postcondition"] = f"And(\n    True,\n    {target['postcondition']}\n)"
        channel = "spec" if index % 2 == 0 else "code"
        prompt = make_prompt(index, channel, a, b)
        for family, model in (("qwen", QWEN), ("oss", OSS)):
            client.call(f"judge-{index}-neutral_style-{family}", model, prompt, 0)

    pending = list(enumerate(CASES))
    while pending:
        ready = []
        for index, case in pending:
            path = client.output / f"gen-{case.name}-spec-initial.json"
            if not path.exists():
                continue
            qwen = json.loads(path.read_text())["response"]
            native = native_prompt(case, "spec")
            oss = client.call(f"origin-{index}-oss", OSS, native, 0.7)
            options = (formulas(payload(qwen)), formulas(payload(oss)))
            for order in (0, 1):
                a, b = options[order], options[1 - order]
                prompt = make_prompt(index, "spec", a, b)
                for family, model in (("qwen", QWEN), ("oss", OSS)):
                    client.call(f"provenance-{index}-{order}-{family}", model, prompt, 0)
            question = (
                "Assess whether the following contract exactly matches the domain and returned "
                "value in the source. The formula language uses SMT integer division. Return "
                "a JSON object with the key verdict, set to PASS, FAIL, or UNKNOWN.\n"
                f"Source: {source_for(index, 'spec')}\nContract: {json.dumps(options[0])}"
            )
            history = (
                {"role": "user", "content": native},
                {"role": "assistant", "content": content(qwen) or "{}"},
            )
            client.call(f"context-{index}-fresh", QWEN, question, 0)
            client.call(f"context-{index}-same", QWEN, question, 0, history)
            ready.append((index, case))
        if not ready:
            time.sleep(5)
        pending = [pair for pair in pending if pair not in ready]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--env", type=Path)
    args = parser.parse_args()
    client = Groq(args.output, args.env, interval=8)
    client.preflight({QWEN, OSS})
    run(client)


if __name__ == "__main__":
    main()
