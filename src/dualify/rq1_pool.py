"""Построение фиксированного пула кандидатов RQ1 и сохранение слотов."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from pathlib import Path
from typing import NoReturn

from dualify.ollama_client import LLMClient
from dualify.rq1_attempt import (
    AttemptError,
    AttemptRecord,
    Channel,
    LogicalCall,
    run_extraction_attempt,
)
from dualify.transcript import RecordingLLMClient, ResumingLLMClient
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
    records: list[AttemptRecord] = []
    artifact_dir.mkdir(parents=True, exist_ok=True)

    for slot_id, channel, temperature in _slot_specs(case, treatment_temperature):
        slot_dir = artifact_dir / slot_id.replace(":", "__")
        result_path = slot_dir / "result.json"
        transcript_path = slot_dir / "transcript.jsonl"

        if result_path.exists():
            record = _load_attempt(result_path)
            if record.slot_id != slot_id or record.status != "completed":
                raise ValueError(f"Повреждён завершённый slot {slot_id}")
            records.append(record)
            continue

        slot_dir.mkdir(parents=True, exist_ok=True)
        transcript_client: RecordingLLMClient | ResumingLLMClient
        if transcript_path.exists():
            transcript_client = ResumingLLMClient.from_path(client, transcript_path)
        else:
            transcript_client = RecordingLLMClient(
                inner=client,
                transcript_path=transcript_path,
                model=model,
                base_url="",
                provider="rq1",
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
        if expected.status != "completed":
            raise PoolIntegrityError(f"Slot {slot_id} не завершён")
        if (
            expected.channel != channel
            or expected.model != model
            or expected.initial_temperature != temperature
            or expected.repair_temperature != 0.0
        ):
            raise PoolIntegrityError(f"Slot {slot_id}: metadata не совпадает с планом")
        transcript_path = result_paths[slot_id].parent / "transcript.jsonl"
        replay_client = _StrictReplayClient(transcript_path, expected.calls)
        actual = run_extraction_attempt(
            replay_client,
            slot_id=slot_id,
            channel=channel,
            case=case,
            model=model,
            initial_temperature=temperature,
            max_transient_retries=0,
        )
        if replay_client.failure is not None:
            raise replay_client.failure
        replay_client.verify_exhausted()
        if actual.status != "completed" or actual.extraction != expected.extraction:
            raise PoolIntegrityError(f"Replay изменил финальный результат slot {slot_id}")
        if [
            (call.stage, call.temperature, call.response) for call in actual.calls
        ] != [
            (call.stage, call.temperature, call.response) for call in expected.calls
        ]:
            raise PoolIntegrityError(f"Replay изменил logical calls slot {slot_id}")
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


class _StrictReplayClient:
    """Последовательно проверяет transcript до передачи ответа extractor-у."""

    def __init__(self, path: Path, expected_calls: list[LogicalCall]) -> None:
        self.path = path
        self.expected_calls = expected_calls
        self.records = _load_transcript_records(path)
        self.cursor = 0
        self.failure: PoolIntegrityError | None = None

    def generate_json(self, prompt: str, temperature: float = 0.0) -> dict:
        if self.failure is not None:
            raise self.failure
        if self.cursor >= len(self.records) or self.cursor >= len(self.expected_calls):
            self._fail("transcript исчерпан раньше extraction")

        record = self.records[self.cursor]
        expected_call = self.expected_calls[self.cursor]
        actual_hash = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
        if record.get("call_index") != self.cursor:
            self._fail("нарушен порядок call_index")
        if record.get("prompt_sha256") != actual_hash:
            self._fail("prompt hash не совпадает")
        if record.get("temperature") != temperature:
            self._fail("temperature не совпадает")
        response = record.get("response")
        if not isinstance(response, dict) or response != expected_call.response:
            self._fail("response не совпадает с candidate record")

        self.cursor += 1
        return response

    def healthcheck(self) -> None:
        return None

    def verify_exhausted(self) -> None:
        if self.cursor != len(self.records) or self.cursor != len(self.expected_calls):
            raise PoolIntegrityError(
                f"Slot {self.path.parent.name}: использовано {self.cursor}, "
                f"transcript={len(self.records)}, calls={len(self.expected_calls)}"
            )

    def _fail(self, message: str) -> NoReturn:
        self.failure = PoolIntegrityError(f"Slot {self.path.parent.name}: {message}")
        raise self.failure


def _load_transcript_records(path: Path) -> list[dict]:
    if not path.exists():
        raise PoolIntegrityError(f"Отсутствует transcript: {path}")
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
        if "transcript_metadata" not in payload:
            records.append(payload)
    return records


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
