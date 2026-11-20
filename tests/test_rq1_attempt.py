from __future__ import annotations

import json
from copy import deepcopy
from typing import Literal

import pytest
import requests

from dualify.phases.p01_spec_to_logic import extract_spec_logic
from dualify.phases.p02_code_to_logic import extract_code_logic
from dualify.rq1_attempt import run_extraction_attempt
from dualify.types import BenchmarkCase

VALID_RESPONSE = {
    "args": ["x"],
    "return_type": "int",
    "domain_constraints": [],
    "postcondition": "ret == x + 1",
    "confidence": "high",
    "notes": "exact",
}

INVALID_RESPONSE = {
    "args": ["x"],
    "return_type": "int",
    "domain_constraints": [],
    "postcondition": "ret == ret",
    "confidence": "low",
    "notes": "invalid tautology",
}


class FakeClient:
    def __init__(self, responses: list[dict | Exception]) -> None:
        self.responses = responses
        self.temperatures: list[float] = []

    def generate_json(self, prompt: str, temperature: float = 0.0) -> dict:
        self.temperatures.append(temperature)
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return deepcopy(response)

    def healthcheck(self) -> None:
        return None


@pytest.fixture
def benchmark_case() -> BenchmarkCase:
    return BenchmarkCase(
        benchmark_id="increment",
        file="increment.py",
        qualname="increment",
        lineno=1,
        signature="increment(x: int)",
        arg_types={"x": "int"},
        return_type="int",
        informal_spec="Return x plus one.",
        extra_context="",
        function_source="def increment(x: int) -> int:\n    return x + 1\n",
    )


@pytest.mark.parametrize("channel", ["spec", "code"])
def test_treatment_uses_temperature_for_initial_call_and_keeps_native_result(
    benchmark_case: BenchmarkCase,
    channel: Literal["spec", "code"],
) -> None:
    client = FakeClient([VALID_RESPONSE])

    record = run_extraction_attempt(
        client,
        slot_id=f"increment:{channel}:treatment:1",
        channel=channel,
        case=benchmark_case,
        model="fake-model",
        initial_temperature=0.7,
    )

    assert record.status == "completed"
    assert record.extraction.postcondition == "ret == x + 1"
    assert record.extraction.extraction_trace == {
        "initial": {
            "domain_constraints": [],
            "postcondition": "ret == x + 1",
            "errors": [],
        },
        "final": {
            "domain_constraints": [],
            "postcondition": "ret == x + 1",
            "degraded": False,
            "degraded_reason": "",
        },
    }
    assert client.temperatures == [0.7]
    assert [call.temperature for call in record.calls] == [0.7]
    assert record.logical_call_count == 1
    assert record.elapsed_seconds >= 0


@pytest.mark.parametrize("channel", ["spec", "code"])
def test_native_repair_always_uses_zero_temperature(
    benchmark_case: BenchmarkCase,
    channel: Literal["spec", "code"],
) -> None:
    client = FakeClient([INVALID_RESPONSE, VALID_RESPONSE])

    record = run_extraction_attempt(
        client,
        slot_id=f"increment:{channel}:treatment:1",
        channel=channel,
        case=benchmark_case,
        model="fake-model",
        initial_temperature=0.7,
    )

    assert record.status == "completed"
    assert record.extraction.postcondition == "ret == x + 1"
    assert client.temperatures == [0.7, 0.0]
    assert [call.temperature for call in record.calls] == [0.7, 0.0]
    assert [call.stage for call in record.calls] == ["initial", "repair"]
    assert [call.response for call in record.calls] == [INVALID_RESPONSE, VALID_RESPONSE]


def test_model_output_errors_finish_as_degraded_candidate(
    benchmark_case: BenchmarkCase,
) -> None:
    invalid_json = json.JSONDecodeError("invalid JSON", "not-json", 0)
    client = FakeClient([invalid_json] * 3)

    record = run_extraction_attempt(
        client,
        slot_id="increment:spec:treatment:1",
        channel="spec",
        case=benchmark_case,
        model="fake-model",
        initial_temperature=0.7,
        max_transient_retries=2,
    )

    assert record.status == "completed"
    assert record.extraction.degraded is True
    assert client.temperatures == [0.7, 0.0, 0.0]
    assert [error.category for error in record.errors] == ["model_output_format"] * 3


def test_ambiguous_response_shape_marks_slot_incomplete(
    benchmark_case: BenchmarkCase,
) -> None:
    client = FakeClient([ValueError("Completion response has no choices")])

    record = run_extraction_attempt(
        client,
        slot_id="increment:spec:treatment:1",
        channel="spec",
        case=benchmark_case,
        model="fake-model",
        initial_temperature=0.7,
    )

    assert record.status == "incomplete"
    assert record.errors[0].category == "ambiguous_provider_failure"


@pytest.mark.parametrize("channel", ["spec", "code"])
def test_zero_temperature_baseline_matches_native_extractor(
    benchmark_case: BenchmarkCase,
    channel: Literal["spec", "code"],
) -> None:
    wrapped_client = FakeClient([INVALID_RESPONSE, VALID_RESPONSE])
    native_client = FakeClient([INVALID_RESPONSE, VALID_RESPONSE])

    record = run_extraction_attempt(
        wrapped_client,
        slot_id=f"increment:{channel}:baseline:0",
        channel=channel,
        case=benchmark_case,
        model="fake-model",
        initial_temperature=0.0,
    )
    if channel == "spec":
        native = extract_spec_logic(
            native_client,
            benchmark_id=benchmark_case.benchmark_id,
            signature=benchmark_case.signature,
            informal_spec=benchmark_case.informal_spec,
            return_type=benchmark_case.return_type,
            extra_context=benchmark_case.extra_context,
            arg_types=benchmark_case.arg_types,
        )
    else:
        native = extract_code_logic(
            native_client,
            benchmark_id=benchmark_case.benchmark_id,
            signature=benchmark_case.signature,
            function_source=benchmark_case.function_source,
            return_type=benchmark_case.return_type,
            extra_context=benchmark_case.extra_context,
            arg_types=benchmark_case.arg_types,
        )

    assert record.extraction == native
    assert wrapped_client.temperatures == native_client.temperatures == [0.0, 0.0]


def test_transient_failure_retries_the_same_logical_call(
    benchmark_case: BenchmarkCase,
) -> None:
    client = FakeClient([requests.ConnectionError("offline"), VALID_RESPONSE])

    record = run_extraction_attempt(
        client,
        slot_id="increment:spec:treatment:1",
        channel="spec",
        case=benchmark_case,
        model="fake-model",
        initial_temperature=0.7,
        max_transient_retries=1,
    )

    assert record.status == "completed"
    assert record.logical_call_count == 1
    assert record.calls[0].dispatch_count == 2
    assert client.temperatures == [0.7, 0.7]
    assert [error.category for error in record.errors] == ["transient_infrastructure"]


def test_exhausted_transient_failure_marks_slot_incomplete(
    benchmark_case: BenchmarkCase,
) -> None:
    client = FakeClient([requests.Timeout("timeout")] * 2)

    record = run_extraction_attempt(
        client,
        slot_id="increment:spec:treatment:1",
        channel="spec",
        case=benchmark_case,
        model="fake-model",
        initial_temperature=0.7,
        max_transient_retries=1,
    )

    assert record.status == "incomplete"
    assert record.extraction.degraded is True
    assert record.calls[0].dispatch_count == 2
    assert len(client.temperatures) == 2
    assert [error.category for error in record.errors] == [
        "transient_infrastructure",
        "transient_infrastructure",
    ]


@pytest.mark.parametrize("status_code", [401, 404])
def test_permanent_config_failure_stops_attempt_with_evidence(
    benchmark_case: BenchmarkCase,
    status_code: int,
) -> None:
    response_body = '{"error":"invalid api key or model"}'
    client = FakeClient([http_error(status_code, response_body)])

    record = run_extraction_attempt(
        client,
        slot_id="increment:code:treatment:1",
        channel="code",
        case=benchmark_case,
        model="fake-model",
        initial_temperature=0.7,
        max_transient_retries=2,
    )

    assert record.status == "permanent_config_failure"
    assert len(client.temperatures) == 1
    assert record.errors[0].category == "permanent_config"
    assert record.errors[0].status_code == status_code
    assert record.errors[0].response_body == response_body


def test_http_output_validation_error_is_not_retried_as_infrastructure(
    benchmark_case: BenchmarkCase,
) -> None:
    client = FakeClient(
        [http_error(400, '{"error":"generated JSON failed schema validation"}'), VALID_RESPONSE]
    )

    record = run_extraction_attempt(
        client,
        slot_id="increment:spec:treatment:1",
        channel="spec",
        case=benchmark_case,
        model="fake-model",
        initial_temperature=0.7,
        max_transient_retries=2,
    )

    assert record.status == "completed"
    assert record.extraction.postcondition == "ret == x + 1"
    assert client.temperatures == [0.7, 0.0]
    assert record.errors[0].category == "model_output_format"
    assert record.errors[0].status_code == 400


def test_request_validation_error_is_permanent_config_failure(
    benchmark_case: BenchmarkCase,
) -> None:
    client = FakeClient([http_error(400, "request schema validation failed: model is required")])

    record = run_extraction_attempt(
        client,
        slot_id="increment:spec:treatment:1",
        channel="spec",
        case=benchmark_case,
        model="fake-model",
        initial_temperature=0.7,
    )

    assert record.status == "permanent_config_failure"
    assert record.errors[0].category == "permanent_config"


def test_error_evidence_redacts_credentials(benchmark_case: BenchmarkCase) -> None:
    error = http_error(401, '{"api_key":"body-secret","error":"unauthorized"}')
    error.args = ("Authorization: Bearer message-secret",)
    client = FakeClient([error])

    record = run_extraction_attempt(
        client,
        slot_id="increment:code:treatment:1",
        channel="code",
        case=benchmark_case,
        model="fake-model",
        initial_temperature=0.7,
    )

    evidence = record.errors[0]
    assert evidence.message == "Authorization: Bearer [REDACTED]"
    assert evidence.response_body == '{"api_key":"[REDACTED]","error":"unauthorized"}'


def http_error(status_code: int, body: str) -> requests.HTTPError:
    response = requests.Response()
    response.status_code = status_code
    response._content = body.encode("utf-8")
    error = requests.HTTPError(f"HTTP {status_code}")
    error.response = response
    return error
