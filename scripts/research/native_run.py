"""Replay a common initial live response, then run original or corrected native repair."""

import argparse
import hashlib
import json
import time
from dataclasses import asdict
from pathlib import Path

from contract_cases import CASES, Case
from generation_run import arg_types
from groq_runs import QWEN, Groq, payload
from pipeline_audit import validation_variant

from dualify.phases.p01_spec_to_logic import extract_spec_logic
from dualify.phases.p02_code_to_logic import extract_code_logic


class TransportFailed(BaseException):
    """Keep infrastructure failures out of native degraded-result handling."""


class NativeClient:
    def __init__(self, client: Groq, prefix: str, initial: dict) -> None:
        self.client = client
        self.prefix = prefix
        self.initial = initial
        self.calls: list[str] = []

    def generate_json(self, prompt: str) -> dict:
        if not self.calls:
            self.calls.append(f"gen-{self.prefix}-initial")
            return payload(self.initial)
        prompt_id = hashlib.sha256(prompt.encode()).hexdigest()[:16]
        slot = f"repair-{self.prefix}-{prompt_id}"
        self.calls.append(slot)
        try:
            return payload(self.client.call(slot, QWEN, prompt, 0))
        except Exception as error:
            raise TransportFailed(str(error)) from error


def run_one(
    client: Groq, case: Case, channel: str, initial: dict, variant: str,
) -> None:
    prefix = f"{case.name}-{channel}"
    result = client.output / f"native-{prefix}-{variant}.json"
    if result.exists():
        return
    adapter = NativeClient(client, prefix, initial)
    extract = extract_spec_logic if channel == "spec" else extract_code_logic
    with validation_variant(variant):
        extraction = extract(
            adapter, f"research::{case.name}", case.signature,
            case.prose if channel == "spec" else case.source, case.return_type,
            arg_types=arg_types(case),
        )
    result.write_text(json.dumps({"extraction": asdict(extraction), "calls": adapter.calls}) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--env", type=Path)
    args = parser.parse_args()
    client = Groq(args.output, args.env, interval=5)
    client.preflight({QWEN})
    todo = [(case, channel) for case in CASES for channel in ("spec", "code")]
    while todo:
        ready = []
        for case, channel in todo:
            path = args.output / f"gen-{case.name}-{channel}-initial.json"
            if path.exists():
                initial = json.loads(path.read_text())["response"]
                for variant in ("baseline", "both"):
                    run_one(client, case, channel, initial, variant)
                ready.append((case, channel))
        if not ready:
            time.sleep(5)
        todo = [pair for pair in todo if pair not in ready]


if __name__ == "__main__":
    main()
