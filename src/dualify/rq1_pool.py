"""Построение фиксированного пула кандидатов RQ1 и сохранение слотов."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from dataclasses import asdict
from pathlib import Path
from typing import NoReturn

import requests

from dualify.ollama_client import LLMClient
from dualify.rq1_attempt import (
    AttemptError,
    AttemptRecord,
    Channel,
    LogicalCall,
    _classify_error,
    run_extraction_attempt,
)
from dualify.types import BenchmarkCase, ExtractionResult


class PoolIntegrityError(RuntimeError):
    """Артефакты пула не доказывают записанный набор кандидатов."""


def run_candidate_pool(
    client: LLMClient,
    *,
    case: BenchmarkCase,
    artifact_dir: Path,
    model: str,
    treatment_temperature: float,
    max_transient_retries: int = 0,
) -> list[AttemptRecord]:
    """Запускает или возобновляет baseline и четыре treatment-слота обоих каналов."""
    slot_specs = _slot_specs(case, treatment_temperature)
    records: list[AttemptRecord] = []
    artifact_dir.mkdir(parents=True, exist_ok=True)
    _ensure_pool_config(
        artifact_dir,
        case=case,
        model=model,
        treatment_temperature=treatment_temperature,
        max_transient_retries=max_transient_retries,
    )

    for slot_id, channel, temperature in slot_specs:
        slot_dir = artifact_dir / slot_id.replace(":", "__")
        result_path = slot_dir / "result.json"
        transcript_path = slot_dir / "transcript.jsonl"

        if result_path.exists():
            record = _load_attempt(result_path)
            _validate_attempt_metadata(
                record,
                slot_id=slot_id,
                channel=channel,
                model=model,
                temperature=temperature,
                max_transient_retries=max_transient_retries,
            )
            records.append(record)
            continue

        slot_dir.mkdir(parents=True, exist_ok=True)
        transcript_client = _PoolTranscriptClient(
            client,
            transcript_path,
            slot_id=slot_id,
            model=model,
            initial_temperature=temperature,
            max_transient_retries=max_transient_retries,
        )

        try:
            record = run_extraction_attempt(
                transcript_client,
                slot_id=slot_id,
                channel=channel,
                case=case,
                model=model,
                initial_temperature=temperature,
                max_transient_retries=max_transient_retries,
            )
        finally:
            transcript_client.close()

        records.append(record)
        if record.status != "completed":
            # Следующие slots нельзя запускать, пока текущий не завершён.
            return records
        _write_attempt_atomically(result_path, record)

    return records


def verify_candidate_pool(
    *,
    artifact_dir: Path,
    case: BenchmarkCase,
    model: str,
    treatment_temperature: float,
) -> list[AttemptRecord]:
    """Строго воспроизводит все slots и отвергает неполные артефакты."""
    pool_config = _ensure_pool_config(
        artifact_dir,
        case=case,
        model=model,
        treatment_temperature=treatment_temperature,
        max_transient_retries=None,
    )
    expected_specs = _slot_specs(case, treatment_temperature)
    result_paths: dict[str, Path] = {}
    records: dict[str, AttemptRecord] = {}

    for path in artifact_dir.glob("*/result.json"):
        record = _load_attempt(path)
        if record.slot_id in records:
            raise PoolIntegrityError(f"Повторный slot ID: {record.slot_id}")
        records[record.slot_id] = record
        result_paths[record.slot_id] = path

    expected_ids = {slot_id for slot_id, _, _ in expected_specs}
    if set(records) != expected_ids:
        missing = sorted(expected_ids - set(records))
        extra = sorted(set(records) - expected_ids)
        raise PoolIntegrityError(f"Неверный набор slots: missing={missing}, extra={extra}")

    replayed: list[AttemptRecord] = []
    for slot_id, channel, temperature in expected_specs:
        expected = records[slot_id]
        _validate_attempt_metadata(
            expected,
            slot_id=slot_id,
            channel=channel,
            model=model,
            temperature=temperature,
            max_transient_retries=pool_config["max_transient_retries"],
        )
        transcript_path = result_paths[slot_id].parent / "transcript.jsonl"
        replay_client = _StrictReplayClient(transcript_path, expected)
        actual = run_extraction_attempt(
            replay_client,
            slot_id=slot_id,
            channel=channel,
            case=case,
            model=model,
            initial_temperature=temperature,
            max_transient_retries=expected.max_transient_retries,
        )
        if replay_client.failure is not None:
            raise replay_client.failure
        replay_client.verify_exhausted()
        if actual.status != "completed" or actual.extraction != expected.extraction:
            raise PoolIntegrityError(f"Replay изменил финальный результат slot {slot_id}")
        if [
            (call.stage, call.temperature, call.dispatch_count, call.response)
            for call in actual.calls
        ] != [
            (call.stage, call.temperature, call.dispatch_count, call.response)
            for call in expected.calls
        ]:
            raise PoolIntegrityError(f"Replay изменил logical calls slot {slot_id}")
        actual_errors = [
            (
                error.call_index,
                error.dispatch_index,
                error.category,
                error.error_type,
                error.status_code,
            )
            for error in actual.errors
        ]
        expected_errors = [
            (
                error.call_index,
                error.dispatch_index,
                error.category,
                error.error_type,
                error.status_code,
            )
            for error in expected.errors
        ]
        if actual_errors != expected_errors:
            raise PoolIntegrityError(f"Replay изменил errors slot {slot_id}")
        replayed.append(actual)

    return replayed


def _slot_specs(
    case: BenchmarkCase,
    treatment_temperature: float,
) -> list[tuple[str, Channel, float]]:
    if treatment_temperature <= 0:
        raise ValueError("treatment_temperature must be positive")
    specs: list[tuple[str, Channel, float]] = []
    channels: tuple[Channel, Channel] = ("spec", "code")
    for channel in channels:
        specs.append((f"{case.benchmark_id}:{channel}:baseline:0", channel, 0.0))
        specs.extend(
            (
                f"{case.benchmark_id}:{channel}:treatment:{index}",
                channel,
                treatment_temperature,
            )
            for index in range(1, 5)
        )
    return specs


class _PoolTranscriptClient:
    """Пишет ответы и классы ошибок, сохраняя префикс при resume."""

    def __init__(
        self,
        inner: LLMClient,
        path: Path,
        *,
        slot_id: str,
        model: str,
        initial_temperature: float,
        max_transient_retries: int,
    ) -> None:
        self.inner = inner
        self.path = path
        metadata = {
            "version": 1,
            "slot_id": slot_id,
            "model": model,
            "initial_temperature": initial_temperature,
            "repair_temperature": 0.0,
            "max_transient_retries": max_transient_retries,
        }
        if path.exists():
            stored_metadata, events = _load_transcript(path)
            if stored_metadata != metadata:
                raise PoolIntegrityError(f"Slot {slot_id}: конфигурация resume не совпадает")
        else:
            events = []
            path.write_text(
                json.dumps({"rq1_slot_metadata": metadata}, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )

        previous_run = max((event["run_index"] for event in events), default=-1)
        self.run_index = previous_run + 1
        self.cached_responses = [
            event
            for event in events
            if event["run_index"] == previous_run and "response" in event
        ]
        self.cached_cursor = 0
        self.next_event_index = len(events)
        self._handle = path.open("a", encoding="utf-8", buffering=1)

    def generate_json(self, prompt: str, temperature: float = 0.0) -> dict:
        prompt_hash = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
        if self.cached_cursor < len(self.cached_responses):
            cached = self.cached_responses[self.cached_cursor]
            if (
                cached.get("prompt_sha256") != prompt_hash
                or cached.get("temperature") != temperature
            ):
                raise PoolIntegrityError(f"Slot {self.path.parent.name}: resume prefix mismatch")
            self.cached_cursor += 1
            response = cached["response"]
            self._append_event(prompt, temperature, response=response)
            return deepcopy(response)

        try:
            response = self.inner.generate_json(prompt, temperature=temperature)
        except Exception as exc:
            category, status_code = _classify_error(exc)
            self._append_event(
                prompt,
                temperature,
                error={
                    "error_type": type(exc).__name__,
                    "category": category,
                    "status_code": status_code,
                },
            )
            raise
        self._append_event(prompt, temperature, response=response)
        return response

    def healthcheck(self) -> None:
        self.inner.healthcheck()

    def close(self) -> None:
        self._handle.close()

    def _append_event(
        self,
        prompt: str,
        temperature: float,
        *,
        response: dict | None = None,
        error: dict | None = None,
    ) -> None:
        event = {
            "event_index": self.next_event_index,
            "run_index": self.run_index,
            "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
            "temperature": temperature,
            "prompt": prompt,
        }
        if error is None:
            event["response"] = response
        else:
            event.update(error)
        self._handle.write(json.dumps(event, ensure_ascii=False) + "\n")
        self._handle.flush()
        self.next_event_index += 1


class _StrictReplayClient:
    """Воспроизводит последний полный run, включая записанные ошибки."""

    def __init__(self, path: Path, expected: AttemptRecord) -> None:
        self.path = path
        metadata, all_events = _load_transcript(path)
        expected_metadata = {
            "version": 1,
            "slot_id": expected.slot_id,
            "model": expected.model,
            "initial_temperature": expected.initial_temperature,
            "repair_temperature": expected.repair_temperature,
            "max_transient_retries": expected.max_transient_retries,
        }
        if metadata != expected_metadata:
            raise PoolIntegrityError(f"Slot {expected.slot_id}: transcript metadata mismatch")
        final_run = max((event["run_index"] for event in all_events), default=-1)
        self.events = [event for event in all_events if event["run_index"] == final_run]
        self.expected_responses = [call.response for call in expected.calls if call.response]
        self.expected_errors = expected.errors
        self.cursor = 0
        self.response_cursor = 0
        self.error_cursor = 0
        self.failure: PoolIntegrityError | None = None

    def generate_json(self, prompt: str, temperature: float = 0.0) -> dict:
        if self.failure is not None:
            raise self.failure
        if self.cursor >= len(self.events):
            self._fail("transcript исчерпан раньше extraction")

        record = self.events[self.cursor]
        actual_hash = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
        if record.get("prompt_sha256") != actual_hash:
            self._fail("prompt hash не совпадает")
        if record.get("temperature") != temperature:
            self._fail("temperature не совпадает")

        self.cursor += 1
        if "error_type" in record:
            if self.error_cursor >= len(self.expected_errors):
                self._fail("лишняя error-запись")
            expected_error = self.expected_errors[self.error_cursor]
            identity = (
                record.get("category"),
                record.get("error_type"),
                record.get("status_code"),
            )
            expected_identity = (
                expected_error.category,
                expected_error.error_type,
                expected_error.status_code,
            )
            if identity != expected_identity:
                self._fail("error identity не совпадает с candidate record")
            self.error_cursor += 1
            raise _exception_from_event(record)

        response = record.get("response")
        if self.response_cursor >= len(self.expected_responses):
            self._fail("лишняя response-запись")
        expected_response = self.expected_responses[self.response_cursor]
        if not isinstance(response, dict) or response != expected_response:
            self._fail("response не совпадает с candidate record")
        self.response_cursor += 1
        return response

    def healthcheck(self) -> None:
        return None

    def verify_exhausted(self) -> None:
        if (
            self.cursor != len(self.events)
            or self.response_cursor != len(self.expected_responses)
            or self.error_cursor != len(self.expected_errors)
        ):
            raise PoolIntegrityError(
                f"Slot {self.path.parent.name}: использовано {self.cursor}, "
                f"events={len(self.events)}, responses={self.response_cursor}, "
                f"errors={self.error_cursor}"
            )

    def _fail(self, message: str) -> NoReturn:
        self.failure = PoolIntegrityError(f"Slot {self.path.parent.name}: {message}")
        raise self.failure


def _load_transcript(path: Path) -> tuple[dict, list[dict]]:
    if not path.exists():
        raise PoolIntegrityError(f"Отсутствует transcript: {path}")
    metadata: dict | None = None
    records: list[dict] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError as exc:
            raise PoolIntegrityError(
                f"Некорректный JSON в {path}, строка {line_number}"
            ) from exc
        if "rq1_slot_metadata" in payload:
            if metadata is not None:
                raise PoolIntegrityError(f"Повторный header в transcript: {path}")
            metadata = payload["rq1_slot_metadata"]
        else:
            records.append(payload)
    if metadata is None:
        raise PoolIntegrityError(f"Отсутствует header в transcript: {path}")
    for index, event in enumerate(records):
        if event.get("event_index") != index:
            raise PoolIntegrityError(f"Нарушен порядок event_index в transcript: {path}")
    return metadata, records


def _exception_from_event(event: dict) -> Exception:
    error_type = event["error_type"]
    category = event["category"]
    if error_type == "JSONDecodeError":
        return json.JSONDecodeError("recorded model output error", "", 0)
    if error_type == "Timeout":
        return requests.Timeout("recorded timeout")
    if error_type == "ConnectionError":
        return requests.ConnectionError("recorded connection error")
    if error_type == "HTTPError":
        response = requests.Response()
        response.status_code = event.get("status_code") or 400
        if category == "model_output_format":
            response._content = b"generated output failed validation"
        elif category == "permanent_config":
            response._content = b"request schema validation failed"
        error = requests.HTTPError(f"HTTP {response.status_code}")
        error.response = response
        return error
    if error_type == "ValueError":
        return ValueError("recorded provider error")
    return RuntimeError(f"recorded {error_type}")


def _ensure_pool_config(
    artifact_dir: Path,
    *,
    case: BenchmarkCase,
    model: str,
    treatment_temperature: float,
    max_transient_retries: int | None,
) -> dict:
    path = artifact_dir / "pool_config.json"
    expected = {
        "benchmark_id": case.benchmark_id,
        "model": model,
        "treatment_temperature": treatment_temperature,
    }
    if max_transient_retries is not None:
        expected["max_transient_retries"] = max_transient_retries
    if not path.exists():
        if max_transient_retries is None:
            raise PoolIntegrityError("Отсутствует конфигурация пула")
        temporary_path = path.with_suffix(".tmp")
        temporary_path.write_text(json.dumps(expected, ensure_ascii=False), encoding="utf-8")
        temporary_path.replace(path)
        return expected

    stored = json.loads(path.read_text(encoding="utf-8"))
    for key, value in expected.items():
        if stored.get(key) != value:
            raise PoolIntegrityError(f"Конфигурация пула не совпадает: {key}")
    return stored


def _validate_attempt_metadata(
    record: AttemptRecord,
    *,
    slot_id: str,
    channel: Channel,
    model: str,
    temperature: float,
    max_transient_retries: int,
) -> None:
    if (
        record.slot_id != slot_id
        or record.channel != channel
        or record.model != model
        or record.initial_temperature != temperature
        or record.repair_temperature != 0.0
        or record.max_transient_retries != max_transient_retries
        or record.status != "completed"
    ):
        raise PoolIntegrityError(f"Slot {slot_id}: metadata не совпадает с конфигурацией")


def _write_attempt_atomically(path: Path, record: AttemptRecord) -> None:
    """Публикует готовый slot одним rename, не оставляя частичный result.json."""
    temporary_path = path.with_suffix(".tmp")
    temporary_path.write_text(
        json.dumps(asdict(record), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temporary_path.replace(path)


def _load_attempt(path: Path) -> AttemptRecord:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return AttemptRecord(
        slot_id=payload["slot_id"],
        channel=payload["channel"],
        model=payload["model"],
        initial_temperature=payload["initial_temperature"],
        repair_temperature=payload["repair_temperature"],
        max_transient_retries=payload["max_transient_retries"],
        status=payload["status"],
        extraction=ExtractionResult(**payload["extraction"]),
        calls=[LogicalCall(**call) for call in payload["calls"]],
        errors=[AttemptError(**error) for error in payload["errors"]],
        elapsed_seconds=payload["elapsed_seconds"],
    )
