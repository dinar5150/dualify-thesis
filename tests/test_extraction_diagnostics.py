"""Extraction error handling and diagnostic regression tests (offline)."""

from __future__ import annotations

import pytest

from dualify.ollama_client import LLMClient
from dualify.phases.p01_spec_to_logic import (
    _typecheck_errors as spec_typecheck_errors,
)
from dualify.phases.p01_spec_to_logic import (
    extract_spec_logic,
)
from dualify.phases.p02_code_to_logic import (
    _typecheck_errors as code_typecheck_errors,
)
from dualify.phases.p02_code_to_logic import (
    extract_code_logic,
)
from dualify.transcript import TranscriptPromptMismatchError


class _FailingClient:
    def healthcheck(self) -> None:
        pass

    def generate_json(self, prompt: str, temperature: float = 0.0) -> dict:
        raise RuntimeError("Do not put the secret key into reports: gsk_test_secret")


class _RepairFailingClient:
    def healthcheck(self) -> None:
        pass

    def __init__(self) -> None:
        self.calls = 0

    def generate_json(self, prompt: str, temperature: float = 0.0) -> dict:
        self.calls += 1
        if self.calls == 1:
            return {"postcondition": "ret == ret"}
        raise TranscriptPromptMismatchError("Recording doesn't match this prompt")


def _extract(channel: str, client: LLMClient):
    if channel == "spec":
        return extract_spec_logic(
            client, "example", "f(x: int) -> int", "Return x.", "int", arg_types={"x": "int"}
        )
    return extract_code_logic(
        client, "example", "f(x: int) -> int", "def f(x: int) -> int: return x",
        "int", arg_types={"x": "int"},
    )


@pytest.mark.parametrize("channel", ["spec", "code"])
def test_provider_failure_is_not_disguised_as_generated_contract(channel: str) -> None:
    with pytest.raises(RuntimeError, match="Do not put"):
        _extract(channel, _FailingClient())


@pytest.mark.parametrize("channel", ["spec", "code"])
def test_replay_mismatch_during_repair_propagates(channel: str) -> None:
    with pytest.raises(TranscriptPromptMismatchError):
        _extract(channel, _RepairFailingClient())


@pytest.mark.parametrize("validator", [spec_typecheck_errors, code_typecheck_errors])
def test_z3_validation_reason_is_visible_without_changing_repair_error(validator) -> None:
    details: list[str] = []
    errors = validator([], "ret == Length(x)", {"x": "int"}, "int", diagnostics=details)
    assert errors == ["postcondition/constraints fail Z3 type check"]
    assert details


class _RepairClient:
    def healthcheck(self) -> None:
        pass

    def __init__(self) -> None:
        self.prompts: list[str] = []

    def generate_json(self, prompt: str, temperature: float = 0.0) -> dict:
        self.prompts.append(prompt)
        return {
            "args": ["x"],
            "return_type": "int",
            "domain_constraints": [],
            "postcondition": "ret == ret" if len(self.prompts) == 1 else "ret == x",
            "confidence": "medium",
            "notes": "test",
        }


@pytest.mark.parametrize("channel", ["spec", "code"])
def test_repair_preserves_trace_without_sending_it_to_model(channel: str) -> None:
    client = _RepairClient()
    result = _extract(channel, client)
    assert result.postcondition == "ret == x"
    assert len(client.prompts) == 2
    assert "initial" in result.extraction_trace
    assert "repair" in result.extraction_trace
    assert "final" in result.extraction_trace
    repair_prompt = client.prompts[1]
    assert '"postcondition": "ret == ret"' in repair_prompt
    assert '"extraction_trace"' not in repair_prompt
    assert '"degraded_reason"' not in repair_prompt
    assert '"z3_diagnostics"' not in repair_prompt
