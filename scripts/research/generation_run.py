"""Paired feedback ablation with one common initial and one further call per arm."""

import argparse
import itertools
import json
import random
from collections.abc import Iterator
from pathlib import Path

from contract_cases import CASES, Case
from groq_runs import QWEN, Groq, content, payload

from dualify.phases.p01_spec_to_logic import extract_spec_logic
from dualify.phases.p02_code_to_logic import extract_code_logic
from dualify.research_contracts import Contract, FormulaError, find_witness


class CapturedPrompt(BaseException):
    pass


class Capture:
    def generate_json(self, prompt: str) -> dict:
        raise CapturedPrompt(prompt)


def arg_types(case: Case) -> dict[str, str]:
    return dict.fromkeys(case.args.split(), "int")


def native_prompt(case: Case, channel: str) -> str:
    extract = extract_spec_logic if channel == "spec" else extract_code_logic
    try:
        extract(
            Capture(), f"research::{case.name}", case.signature,
            case.prose if channel == "spec" else case.source, case.return_type,
            arg_types=arg_types(case),
        )
    except CapturedPrompt as captured:
        return str(captured)
    raise AssertionError("Extractor did not request an initial generation")


def code_examples(case: Case, radius: int) -> Iterator[tuple[tuple[int, ...], int | None]]:
    # Only fixed repository fixtures are executed. Model output is parsed by the scalar DSL.
    namespace: dict = {}
    exec(case.source, namespace)
    function = namespace[case.name]
    values = [0, *itertools.chain.from_iterable((i, -i) for i in range(1, radius + 1))]
    for inputs in itertools.product(values, repeat=len(case.args.split())):
        try:
            yield inputs, function(*inputs)
        except ValueError:
            yield inputs, None


def revision_prompt(
    case: Case, channel: str, initial: dict, *, feedback: bool,
) -> tuple[tuple[dict[str, str], ...], str]:
    history = (
        {"role": "user", "content": native_prompt(case, channel)},
        {"role": "assistant", "content": content(initial) or "{}"},
    )
    prompt = (
        "Recheck the proposed contract against the source. Preserve correct clauses and "
        "revise only where needed. Express the exact domain and return behavior. "
        "Return a complete replacement JSON object with the original keys."
    )
    if feedback:
        candidate = payload(initial)
        try:
            contract = Contract(
                arg_types(case), case.return_type,
                candidate.get("domain_constraints"), candidate.get("postcondition"),
            )
        except FormulaError as error:
            return history, f"{prompt}\nThe typed formula check rejected the proposal: {error}."
        examples = case.examples if channel == "spec" else code_examples(case, 4)
        witness = find_witness(contract, examples)
        if witness:
            actual = next(output for inputs, output in (
                case.examples if channel == "spec" else code_examples(case, 4)
            ) if inputs == tuple(witness["args"].values()))
            source_answer = (
                'rejects that input' if actual is None else f'returns {json.dumps(actual)}'
            )
            prompt += (
                "\nThe following counterexample is verified by "
                f"{'the stated requirements' if channel == 'spec' else 'executing the function'}. "
                f"{json.dumps(witness)}. The source {source_answer}. "
                "In the formula language integer division uses SMT rounding."
            )
    return history, prompt


def run(client: Groq) -> None:
    cells = [(case, channel) for case in CASES for channel in ("spec", "code")]
    rng = random.Random(20261125)
    rng.shuffle(cells)
    for case, channel in cells:
        prefix = f"gen-{case.name}-{channel}"
        native = native_prompt(case, channel)
        initial = client.call(f"{prefix}-initial", QWEN, native, 0.7)
        arms = ["fresh", "revision", "witness"]
        rng.shuffle(arms)
        for arm in arms:
            if arm == "fresh":
                client.call(f"{prefix}-{arm}", QWEN, native, 0.7)
            else:
                history, prompt = revision_prompt(case, channel, initial, feedback=arm == "witness")
                client.call(f"{prefix}-{arm}", QWEN, prompt, 0.7, history)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--env", type=Path)
    parser.add_argument("--interval", type=float, default=3)
    args = parser.parse_args()
    client = Groq(args.output, args.env, interval=args.interval)
    client.preflight({QWEN})
    run(client)


if __name__ == "__main__":
    main()
