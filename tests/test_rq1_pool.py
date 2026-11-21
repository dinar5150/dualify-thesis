"""Проверки публичного offline интерфейса: отдельные attempts → records → offline-read."""

from __future__ import annotations

import contextlib
import json
import shutil
from collections.abc import Sequence
from copy import deepcopy
from pathlib import Path
from typing import Literal

import pytest
import requests

from dualify.ollama_client import LLMClient, OpenAICompatibleClient
from dualify.rq1_attempt import run_extraction_attempt
from dualify.rq1_pool import PoolIntegrityError, run_candidate_pool, verify_candidate_pool
from dualify.transcript import RecordingLLMClient, ReplayLLMClient, ResumingLLMClient
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
    def __init__(self, responses: Sequence[dict | BaseException]) -> None:
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


def _run(tmp_path: Path, client: LLMClient, **kwargs: int) -> list:
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


@pytest.mark.parametrize("kind", ["replay", "wrapped_replay", "wrapped_resume"])
def test_cached_client_cannot_fill_ten_slots_from_two_responses(
    tmp_path: Path, kind: str,
) -> None:
    source = FakeClient([VALID] * 2)
    transcript = tmp_path / "source.jsonl"
    def record_to(client: LLMClient, path: Path) -> RecordingLLMClient:
        return RecordingLLMClient(client, path, model="fake-model", base_url="", provider="fake")

    recording = record_to(source, transcript)
    try:
        channels: tuple[Literal["spec"], Literal["code"]] = ("spec", "code")
        for channel in channels:
            record = run_extraction_attempt(
                recording, slot_id=channel, channel=channel, case=_case(),
                model="fake-model", initial_temperature=0.7,
            )
            assert record.status == "completed"
    finally:
        recording.close()

    cached: ReplayLLMClient | ResumingLLMClient
    if kind == "wrapped_resume":
        cached = ResumingLLMClient.from_path(FakeClient([VALID] * 10), transcript)
    else:
        cached = ReplayLLMClient.from_path(transcript, match_by_prompt=True)
    client: LLMClient = cached
    wrappers = []
    if kind != "replay":
        for index in range(2):
            wrapped = record_to(client, tmp_path / f"wrapped-{index}.jsonl")
            wrappers.append(wrapped)
            client = wrapped
    try:
        pool = tmp_path / "pool"
        with pytest.raises(ValueError, match="replay"):
            _run(pool, client)
        assert len(source.calls) == 2
        assert not list(pool.glob("*/result.json"))
    finally:
        for wrapped in wrappers:
            wrapped.close()
        if isinstance(cached, ResumingLLMClient):
            cached.close()


def test_live_pool_rejects_unknown_client(tmp_path: Path) -> None:
    fake = FakeClient([VALID] * 10)
    with pytest.raises(ValueError, match="HTTP"):
        run_candidate_pool(
            fake, case=_case(), artifact_dir=tmp_path, model="fake-model",
            provider="groq", treatment_temperature=0.7,
        )
    assert not fake.calls


def test_live_resume_refuses_endpoint_change(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = []

    def post(url: str, **kwargs: object) -> requests.Response:
        calls.append(url)
        response = requests.Response()
        response.status_code = 401 if len(calls) == 2 else 200
        response._content = json.dumps({
            "choices": [{"message": {"content": json.dumps(VALID)}, "text": json.dumps(VALID)}],
        }).encode()
        return response

    monkeypatch.setattr(requests, "post", post)
    def run(client: OpenAICompatibleClient) -> list:
        return run_candidate_pool(
            client, case=_case(), artifact_dir=tmp_path, model="fake-model",
            provider="groq", treatment_temperature=0.7,
        )

    chat = OpenAICompatibleClient("fake-model", "https://provider.invalid", fixed_chat_mode=True)
    records = run(chat)
    assert [record.status for record in records] == ["completed", "permanent_config_failure"]

    wrong_mode = OpenAICompatibleClient(
        "fake-model", "https://provider.invalid", fixed_chat_mode=False,
    )
    with pytest.raises(PoolIntegrityError, match="endpoint"):
        run(wrong_mode)
    wrong_model = OpenAICompatibleClient(
        "other-model", "https://provider.invalid", fixed_chat_mode=True,
    )
    with pytest.raises(ValueError, match="model"):
        run(wrong_model)
    assert len(calls) == 2
    assert len(run(chat)) == 10
    assert len(calls) == 11


def test_resume_skips_completed_slots(tmp_path: Path) -> None:
    original = _run(tmp_path, FakeClient([VALID] * 10))
    empty = FakeClient([])

    assert _run(tmp_path, empty) == original
    assert empty.calls == []


def test_transient_failure_stays_incomplete_and_blocks_analytics(tmp_path: Path) -> None:
    fake = FakeClient([VALID, requests.Timeout("connection timeout")])
    partial = _run(tmp_path, fake)
    assert [record.status for record in partial] == ["completed", "incomplete"]
    (completed,) = tmp_path.glob("*/result.json")
    original = completed.read_bytes()
    (failure,) = tmp_path.glob("*/failure.json")
    evidence = json.loads(failure.read_text())
    assert evidence["slot_id"] == partial[1].slot_id
    assert evidence["status"] == "incomplete"
    assert evidence["errors"][0]["message"] == "connection timeout"
    assert evidence["elapsed_seconds"] >= 0
    with pytest.raises(PoolIntegrityError, match="incomplete"):
        _read(tmp_path)

    recovery = FakeClient([VALID] * 9)
    assert len(_run(tmp_path, recovery)) == len(_read(tmp_path)) == 10
    assert len(recovery.calls) == 9
    assert completed.read_bytes() == original
    assert json.loads(failure.read_text()) == evidence


def test_interrupt_keeps_completed_prefix_for_simple_resume(tmp_path: Path) -> None:
    with contextlib.suppress(KeyboardInterrupt):
        _run(tmp_path, FakeClient([VALID] * 3 + [KeyboardInterrupt()]))

    assert len(list(tmp_path.glob("*/result.json"))) == 3
    continuation = FakeClient([VALID] * 7)
    records = _run(tmp_path, continuation)
    assert len(continuation.calls) == 7
    assert len(records) == 10
    assert len(_read(tmp_path)) == 10


def test_interrupted_config_write_can_resume(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    write_text = Path.write_text

    def interrupted_write(path: Path, data: str, *, encoding: str) -> int:
        write_text(path, data[:10], encoding=encoding)
        raise KeyboardInterrupt

    with monkeypatch.context() as patch, pytest.raises(KeyboardInterrupt):
        patch.setattr(Path, "write_text", interrupted_write)
        _run(tmp_path, FakeClient([]))

    client = FakeClient([VALID] * 10)
    assert len(_run(tmp_path, client)) == len(_read(tmp_path)) == 10
    assert len(client.calls) == 10


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


@pytest.mark.parametrize(
    ("section", "field", "value"),
    [
        ("extraction", "domain_constraints", None),
        ("extraction", "domain_constraints", [1]),
        ("extraction", "postcondition", None),
        ("calls", "dispatch_count", "1"),
        ("calls", "dispatch_count", 99),
        ("calls", "response", None),
        ("record", "slot_id", []),
    ],
)
def test_offline_read_diagnoses_invalid_record_fields(
    tmp_path: Path, section: str, field: str, value: object,
) -> None:
    _run(tmp_path, FakeClient([VALID] * 10))
    path = next(tmp_path.glob("*/result.json"))
    data = json.loads(path.read_text())
    target = data if section == "record" else data[section]
    if section == "calls":
        target = target[0]
    target[field] = value
    path.write_text(json.dumps(data))

    with pytest.raises(PoolIntegrityError) as exc:
        _read(tmp_path)
    assert str(path) in str(exc.value)
    assert field in str(exc.value)


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
