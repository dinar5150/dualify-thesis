"""Проверки публичного offline интерфейса: отдельные attempts → records → offline-read."""

from __future__ import annotations

import contextlib
import json
import shutil
from copy import deepcopy
from pathlib import Path

import pytest
import requests

from dualify.rq1_pool import PoolIntegrityError, run_candidate_pool, verify_candidate_pool
from dualify.types import BenchmarkCase

VALID = {
    "args": ["x"],
    "return_type": "int",
    "domain_constraints": [],
    "postcondition": "ret == x + 1",
    "confidence": "high",
    "notes": "repeated text is allowed",
}
INVALID = {
    **VALID,
    "postcondition": "ret == ret",
    "confidence": "low",
}


class FakeClient:
    def __init__(self, responses: list[dict | BaseException]) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[str, float]] = []

    def generate_json(self, prompt: str, temperature: float = 0.0) -> dict:
        self.calls.append((prompt, temperature))
        result = self.responses.pop(0)
        if isinstance(result, BaseException):
            raise result
        return deepcopy(result)

    def healthcheck(self) -> None:
        pass


def _case() -> BenchmarkCase:
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


def _run(tmp_path: Path, client: FakeClient, **kwargs: int) -> list:
    return run_candidate_pool(
        client,
        case=_case(),
        artifact_dir=tmp_path,
        model="fake-model",
        provider="fake",
        treatment_temperature=0.7,
        **kwargs,
    )


def _read(tmp_path: Path) -> list:
    return verify_candidate_pool(
        artifact_dir=tmp_path,
        case=_case(),
        model="fake-model",
        provider="fake",
        treatment_temperature=0.7,
    )


def test_ten_distinct_attempts_with_same_output_are_saved_and_read_offline(
    tmp_path: Path,
) -> None:
    fake = FakeClient([VALID] * 10)
    records = _run(tmp_path, fake)

    assert len(fake.calls) == len(records) == 10
    assert len({r.slot_id for r in records}) == 10
    assert [r.initial_temperature for r in records] == [
        0.0, 0.7, 0.7, 0.7, 0.7,
        0.0, 0.7, 0.7, 0.7, 0.7,
    ]
    assert [temperature for _, temperature in fake.calls] == [
        r.initial_temperature for r in records
    ]
    assert {r.extraction.postcondition for r in records} == {"ret == x + 1"}
    assert len(list(tmp_path.glob("*/result.json"))) == 10
    assert not list(tmp_path.glob("*/transcript.jsonl"))
    assert _read(tmp_path) == records


def test_resume_skips_completed_slots(tmp_path: Path) -> None:
    original = _run(tmp_path, FakeClient([VALID] * 10))
    empty = FakeClient([])

    assert _run(tmp_path, empty) == original
    assert empty.calls == []


def test_transient_failure_stays_incomplete_and_blocks_analytics(tmp_path: Path) -> None:
    fake = FakeClient([requests.Timeout("connection timeout")])
    partial = _run(tmp_path, fake)
    assert len(partial) == 1
    assert partial[0].status == "incomplete"
    assert list(tmp_path.glob("*/result.json")) == []
    with pytest.raises(PoolIntegrityError, match="missing"):
        _read(tmp_path)

    recovery = FakeClient([VALID] * 10)
    assert len(_run(tmp_path, recovery)) == 10
    assert len(recovery.calls) == 10


def test_interrupt_keeps_completed_prefix_for_simple_resume(tmp_path: Path) -> None:
    with contextlib.suppress(KeyboardInterrupt):
        _run(tmp_path, FakeClient([VALID] * 3 + [KeyboardInterrupt()]))

    assert len(list(tmp_path.glob("*/result.json"))) == 3
    continuation = FakeClient([VALID] * 7)
    records = _run(tmp_path, continuation)
    assert len(continuation.calls) == 7
    assert len(records) == 10
    assert len(_read(tmp_path)) == 10


def test_finished_degraded_output_is_not_resampled(tmp_path: Path) -> None:
    # Native extractor делает свои repairs, затем фиксирует degraded result.
    fake = FakeClient([INVALID] * 3 + [VALID] * 9)
    records = _run(tmp_path, fake)
    assert records[0].status == "completed"
    assert records[0].extraction.degraded is True
    assert len(fake.calls) == 12
    assert _run(tmp_path, FakeClient([]))[0].extraction.degraded is True


@pytest.mark.parametrize("bad", ["missing", "duplicate", "metadata", "corrupt"])
def test_offline_read_rejects_incomplete_or_invalid_pool(tmp_path: Path, bad: str) -> None:
    _run(tmp_path, FakeClient([VALID] * 10))
    path = next(tmp_path.glob("*/result.json"))

    if bad == "missing":
        path.unlink()
    elif bad == "duplicate":
        duplicate = tmp_path / "duplicate"
        duplicate.mkdir()
        shutil.copy(path, duplicate / "result.json")
    elif bad == "metadata":
        data = json.loads(path.read_text())
        data["initial_temperature"] = 9.0
        path.write_text(json.dumps(data))
    else:
        path.write_text("not-json")

    with pytest.raises(PoolIntegrityError):
        _read(tmp_path)


def test_config_mismatch_is_detected_before_generating(tmp_path: Path) -> None:
    _run(tmp_path, FakeClient([VALID] * 10))
    with pytest.raises(PoolIntegrityError, match="Конфигурация"):
        run_candidate_pool(
            FakeClient([]),
            case=_case(),
            artifact_dir=tmp_path,
            model="different-model",
            provider="fake",
            treatment_temperature=0.7,
        )


def test_nonpositive_temperature_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="positive"):
        run_candidate_pool(
            FakeClient([]),
            case=_case(),
            artifact_dir=tmp_path,
            model="fake-model",
            provider="fake",
            treatment_temperature=0.0,
        )


def test_no_new_samples_are_generated_by_offline_read(tmp_path: Path) -> None:
    _run(tmp_path, FakeClient([VALID] * 10))
    # Reader не принимает LLM client: только открывает сохранённые records.
    assert len(_read(tmp_path)) == 10
