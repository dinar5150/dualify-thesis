from __future__ import annotations

import contextlib
import json
import shutil
from collections.abc import Sequence
from copy import deepcopy
from pathlib import Path

import pytest
import requests

from dualify.rq1_pool import PoolIntegrityError, run_candidate_pool, verify_candidate_pool
from dualify.types import BenchmarkCase

VALID_RESPONSE = {
    "args": ["x"],
    "return_type": "int",
    "domain_constraints": [],
    "postcondition": "ret == x + 1",
    "confidence": "high",
    "notes": "same response is still a separate attempt",
}

INVALID_RESPONSE = {
    "args": ["x"],
    "return_type": "int",
    "domain_constraints": [],
    "postcondition": "ret == ret",
    "confidence": "low",
    "notes": "requires repair",
}


class FakeClient:
    def __init__(self, responses: Sequence[dict | BaseException]) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[str, float]] = []

    def generate_json(self, prompt: str, temperature: float = 0.0) -> dict:
        self.calls.append((prompt, temperature))
        response = self.responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return deepcopy(response)

    def healthcheck(self) -> None:
        return None


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


def test_pool_records_baseline_and_four_treatment_slots_per_channel(
    tmp_path: Path,
) -> None:
    client = FakeClient([VALID_RESPONSE] * 10)

    records = run_candidate_pool(
        client,
        case=benchmark_case(),
        artifact_dir=tmp_path,
        model="fake-model",
        provider="fake",
        treatment_temperature=0.7,
    )

    assert len(records) == 10
    assert len({record.slot_id for record in records}) == 10
    assert {record.status for record in records} == {"completed"}
    assert sum(record.initial_temperature == 0.0 for record in records) == 2
    assert sum(record.initial_temperature == 0.7 for record in records) == 8
    assert {record.extraction.postcondition for record in records} == {"ret == x + 1"}
    assert len(list(tmp_path.glob("*/result.json"))) == 10
    assert len(list(tmp_path.glob("*/transcript.jsonl"))) == 10


def test_pool_requires_positive_treatment_temperature(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="positive"):
        run_candidate_pool(
            FakeClient([]),
            case=benchmark_case(),
            artifact_dir=tmp_path,
            model="fake-model",
            provider="fake",
            treatment_temperature=0.0,
        )


def test_completed_pool_rejects_changed_sampling_configuration(tmp_path: Path) -> None:
    _record_pool(tmp_path)

    with pytest.raises(PoolIntegrityError, match="[Кк]онфигурац"):
        run_candidate_pool(
            FakeClient([]),
            case=benchmark_case(),
            artifact_dir=tmp_path,
            model="fake-model",
            provider="fake",
            treatment_temperature=0.8,
        )


def test_unresolved_infrastructure_failure_blocks_campaign_at_same_slot(
    tmp_path: Path,
) -> None:
    client = FakeClient([requests.Timeout("offline")])

    records = run_candidate_pool(
        client,
        case=benchmark_case(),
        artifact_dir=tmp_path,
        model="fake-model",
        provider="fake",
        treatment_temperature=0.7,
    )

    assert len(records) == 1
    assert records[0].slot_id == "increment:spec:baseline:0"
    assert records[0].status == "incomplete"
    assert list(tmp_path.glob("*/result.json")) == []
    assert len(client.calls) == 1
    transcript = next(tmp_path.glob("*/transcript.jsonl"))
    events = [json.loads(line) for line in transcript.read_text().splitlines()]
    assert events[1]["error_type"] == "Timeout"


def test_interrupted_slot_resumes_saved_prefix_and_completed_pool_is_idempotent(
    tmp_path: Path,
) -> None:
    first_client = FakeClient(
        [VALID_RESPONSE] * 3 + [INVALID_RESPONSE, KeyboardInterrupt()]
    )

    with contextlib.suppress(KeyboardInterrupt):
        run_candidate_pool(
            first_client,
            case=benchmark_case(),
            artifact_dir=tmp_path,
            model="fake-model",
            provider="fake",
            treatment_temperature=0.7,
        )

    assert len(list(tmp_path.glob("*/result.json"))) == 3

    resume_client = FakeClient([VALID_RESPONSE] * 7)
    records = run_candidate_pool(
        resume_client,
        case=benchmark_case(),
        artifact_dir=tmp_path,
        model="fake-model",
        provider="fake",
        treatment_temperature=0.7,
    )

    assert len(records) == 10
    assert len(resume_client.calls) == 7
    resumed = next(
        record for record in records if record.slot_id == "increment:spec:treatment:3"
    )
    assert [call.response for call in resumed.calls] == [INVALID_RESPONSE, VALID_RESPONSE]

    no_network_client = FakeClient([])
    repeated = run_candidate_pool(
        no_network_client,
        case=benchmark_case(),
        artifact_dir=tmp_path,
        model="fake-model",
        provider="fake",
        treatment_temperature=0.7,
    )

    assert len(repeated) == 10
    assert no_network_client.calls == []


def test_strict_replay_reproduces_complete_pool_without_network(tmp_path: Path) -> None:
    recorded = run_candidate_pool(
        FakeClient([VALID_RESPONSE] * 10),
        case=benchmark_case(),
        artifact_dir=tmp_path,
        model="fake-model",
        provider="fake",
        treatment_temperature=0.7,
    )

    replayed = verify_candidate_pool(
        artifact_dir=tmp_path,
        case=benchmark_case(),
        model="fake-model",
        provider="fake",
        treatment_temperature=0.7,
    )

    assert [record.slot_id for record in replayed] == [record.slot_id for record in recorded]
    assert [record.extraction for record in replayed] == [
        record.extraction for record in recorded
    ]


def _record_pool(path: Path) -> None:
    run_candidate_pool(
        FakeClient([VALID_RESPONSE] * 10),
        case=benchmark_case(),
        artifact_dir=path,
        model="fake-model",
        provider="fake",
        treatment_temperature=0.7,
    )


def _verify_pool(path: Path) -> None:
    verify_candidate_pool(
        artifact_dir=path,
        case=benchmark_case(),
        model="fake-model",
        provider="fake",
        treatment_temperature=0.7,
    )


def test_strict_replay_rejects_missing_llm_record_caught_by_native_extractor(
    tmp_path: Path,
) -> None:
    _record_pool(tmp_path)
    transcript = next(tmp_path.glob("*/transcript.jsonl"))
    lines = transcript.read_text(encoding="utf-8").splitlines()
    transcript.write_text(lines[0] + "\n", encoding="utf-8")

    with pytest.raises(PoolIntegrityError, match="исчерпан"):
        _verify_pool(tmp_path)


@pytest.mark.parametrize("corruption", ["extra", "prompt", "temperature", "response"])
def test_strict_replay_rejects_corrupt_llm_record(
    tmp_path: Path,
    corruption: str,
) -> None:
    _record_pool(tmp_path)
    transcript = next(tmp_path.glob("*/transcript.jsonl"))
    lines = [json.loads(line) for line in transcript.read_text().splitlines()]
    record = lines[1]
    if corruption == "extra":
        lines.append(record.copy())
    elif corruption == "prompt":
        record["prompt_sha256"] = "0" * 64
    elif corruption == "temperature":
        record["temperature"] = 123.0
    else:
        record["response"]["notes"] = "different recorded identity"
    transcript.write_text("".join(json.dumps(line) + "\n" for line in lines))

    with pytest.raises(PoolIntegrityError):
        _verify_pool(tmp_path)


def test_strict_replay_rejects_missing_and_duplicate_slot_ids(tmp_path: Path) -> None:
    _record_pool(tmp_path)
    result = next(tmp_path.glob("*/result.json"))
    hidden = result.with_suffix(".missing")
    result.rename(hidden)
    with pytest.raises(PoolIntegrityError, match="missing"):
        _verify_pool(tmp_path)

    result = hidden.rename(result)
    duplicate_dir = tmp_path / "duplicate"
    duplicate_dir.mkdir()
    shutil.copy(result, duplicate_dir / "result.json")
    with pytest.raises(PoolIntegrityError, match="Повторный slot ID"):
        _verify_pool(tmp_path)


def test_strict_replay_rejects_candidate_metadata_mismatch(tmp_path: Path) -> None:
    _record_pool(tmp_path)
    result = next(tmp_path.glob("*/result.json"))
    payload = json.loads(result.read_text())
    payload["initial_temperature"] = 123.0
    result.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(PoolIntegrityError, match="metadata"):
        _verify_pool(tmp_path)


def test_degraded_but_completed_output_is_saved_and_replayed(tmp_path: Path) -> None:
    records = run_candidate_pool(
        FakeClient([INVALID_RESPONSE] * 3 + [VALID_RESPONSE] * 9),
        case=benchmark_case(),
        artifact_dir=tmp_path,
        model="fake-model",
        provider="fake",
        treatment_temperature=0.7,
    )

    assert records[0].status == "completed"
    assert records[0].extraction.degraded is True
    replayed = verify_candidate_pool(
        artifact_dir=tmp_path,
        case=benchmark_case(),
        model="fake-model",
        provider="fake",
        treatment_temperature=0.7,
    )
    assert replayed[0].extraction == records[0].extraction


def test_model_output_exceptions_are_saved_and_replayed(tmp_path: Path) -> None:
    invalid_json = json.JSONDecodeError("bad JSON", "not-json", 0)
    records = run_candidate_pool(
        FakeClient([invalid_json] * 3 + [VALID_RESPONSE] * 9),
        case=benchmark_case(),
        artifact_dir=tmp_path,
        model="fake-model",
        provider="fake",
        treatment_temperature=0.7,
    )

    assert records[0].status == "completed"
    assert records[0].extraction.degraded is True
    replayed = verify_candidate_pool(
        artifact_dir=tmp_path,
        case=benchmark_case(),
        model="fake-model",
        provider="fake",
        treatment_temperature=0.7,
    )
    assert replayed[0].extraction == records[0].extraction


def test_empty_json_response_is_saved_and_replayed(tmp_path: Path) -> None:
    records = run_candidate_pool(
        FakeClient([{}, VALID_RESPONSE] + [VALID_RESPONSE] * 9),
        case=benchmark_case(),
        artifact_dir=tmp_path,
        model="fake-model",
        provider="fake",
        treatment_temperature=0.7,
    )

    assert records[0].status == "completed"
    replayed = verify_candidate_pool(
        artifact_dir=tmp_path,
        case=benchmark_case(),
        model="fake-model",
        provider="fake",
        treatment_temperature=0.7,
    )
    assert replayed[0].extraction == records[0].extraction


def test_resume_keeps_retries_before_successful_prefix(tmp_path: Path) -> None:
    first_client = FakeClient(
        [requests.Timeout("temporary"), INVALID_RESPONSE, KeyboardInterrupt()]
    )
    with contextlib.suppress(KeyboardInterrupt):
        run_candidate_pool(
            first_client,
            case=benchmark_case(),
            artifact_dir=tmp_path,
            model="fake-model",
            provider="fake",
            treatment_temperature=0.7,
            max_transient_retries=1,
        )

    records = run_candidate_pool(
        FakeClient([VALID_RESPONSE] * 10),
        case=benchmark_case(),
        artifact_dir=tmp_path,
        model="fake-model",
        provider="fake",
        treatment_temperature=0.7,
        max_transient_retries=1,
    )

    assert records[0].calls[0].dispatch_count == 2
    assert [error.category for error in records[0].errors] == [
        "transient_infrastructure"
    ]
    replayed = verify_candidate_pool(
        artifact_dir=tmp_path,
        case=benchmark_case(),
        model="fake-model",
        provider="fake",
        treatment_temperature=0.7,
    )
    assert replayed[0].calls[0].dispatch_count == 2
