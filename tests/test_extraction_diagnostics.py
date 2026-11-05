"""Offline regression tests for diagnostic-only extraction instrumentation."""

from __future__ import annotations

import pytest

from dualify.phases.p01_spec_to_logic import (
    _typecheck_errors as spec_typecheck_errors,
    extract_spec_logic,
)
from dualify.phases.p02_code_to_logic import (
    _typecheck_errors as code_typecheck_errors,
    extract_code_logic,
)


class _FailingClient:
    def generate_json(self, prompt: str, temperature: float = 0.0) -> dict:
        raise RuntimeError("Do not put the secret key into reports: gsk_test_secret")


@pytest.mark.parametrize("channel", ["spec", "code"])
def test_api_failure_type_is_recorded_without_credentials(channel: str) -> None:
    client = _FailingClient()
    if channel == "spec":
        result = extract_spec_logic(client, "example", "f(x: int) -> int", "Return x.", "int")
    else:
        result = extract_code_logic(
            client, "example", "f(x: int) -> int", "def f(x: int) -> int: return x", "int"
        )
    assert result.degraded is True
    assert result.postcondition == "ret == ret"
    for stage in ("initial", "repair", "safe_repair"):
        entry = result.extraction_trace[stage]
        assert entry["llm_error"] == "RuntimeError"
        assert "gsk_test_secret" not in str(entry)


@pytest.mark.parametrize("validator", [spec_typecheck_errors, code_typecheck_errors])
def test_z3_validation_reason_is_visible_without_changing_repair_error(validator) -> None:
    details: list[str] = []
    # Length() requires a sequence/string, but x has integer type.
    # This remains a real Z3 type error after fixing the empty benchmark ID bug.
    errors = validator(
        [], "ret == Length(x)", {"x": "int"}, "int", diagnostics=details
    )
    assert errors == ["postcondition/constraints fail Z3 type check"]
    assert details, "The actual Z3 type mismatch should be recorded for diagnostics"


class _RepairClient:
    def __init__(self) -> None:
        self.calls = 0

    def generate_json(self, prompt: str, temperature: float = 0.0) -> dict:
        self.calls += 1
        return {
            "args": ["x"],
            "return_type": "int",
            "domain_constraints": [],
            "postcondition": "ret == ret" if self.calls == 1 else "ret == x",
            "confidence": "medium",
            "notes": "test",
        }


def test_successful_repair_preserves_initial_trace() -> None:
    client = _RepairClient()
    result = extract_spec_logic(
        client, "example", "f(x: int) -> int", "Return x.", "int", arg_types={"x": "int"}
    )
    assert result.postcondition == "ret == x"
    assert client.calls == 2
    assert "initial" in result.extraction_trace
    assert "repair" in result.extraction_trace
    assert "final" in result.extraction_trace
