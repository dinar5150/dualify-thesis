"""Минимальный RQ1 sampling runner: отдельные attempts и offline-чтение результатов."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict
from pathlib import Path

from dualify.ollama_client import LLMClient
from dualify.rq1_attempt import (
    AttemptError,
    AttemptRecord,
    Channel,
    LogicalCall,
    run_extraction_attempt,
    validate_sampling_client,
)
from dualify.types import BenchmarkCase, ExtractionResult


class PoolIntegrityError(RuntimeError):
    """Записанные данные не позволяют честно оценить полный пул."""


def _slot_specs(case: BenchmarkCase, temperature: float) -> list[tuple[str, Channel, float]]:
    if temperature <= 0:
        raise ValueError("treatment_temperature must be positive")
    specs: list[tuple[str, Channel, float]] = []
    channels: tuple[Channel, Channel] = ("spec", "code")
    for channel in channels:
        specs.append((f"{case.benchmark_id}:{channel}:baseline:0", channel, 0.0))
        for index in range(1, 5):
            specs.append(
                (f"{case.benchmark_id}:{channel}:treatment:{index}", channel, temperature)
            )
    return specs


def _config(
    directory: Path,
    *,
    case: BenchmarkCase,
    model: str,
    provider: str,
    temperature: float,
    retries: int | None,
    create: bool,
    endpoint: str | None = None,
) -> dict:
    path = directory / "pool_config.json"
    expected = {
        "benchmark_id": case.benchmark_id,
        "model": model,
        "provider": provider,
        "treatment_temperature": temperature,
    }
    if retries is not None:
        expected["max_transient_retries"] = retries
    if endpoint is not None:
        # Сверяем endpoint при resume, сохраняя только его отпечаток.
        expected["endpoint_sha256"] = hashlib.sha256(endpoint.encode()).hexdigest()

    if not path.exists():
        if not create:
            raise PoolIntegrityError("Отсутствует конфигурация пула")
        _write_json_atomically(path, expected)
        return expected

    try:
        stored = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise PoolIntegrityError("Некорректная конфигурация пула") from exc
    if not isinstance(stored, dict):
        raise PoolIntegrityError("Некорректная конфигурация пула")
    for key, value in expected.items():
        if stored.get(key) != value:
            raise PoolIntegrityError(f"Конфигурация пула не совпадает: {key}")
    if not isinstance(stored.get("max_transient_retries"), int):
        raise PoolIntegrityError("В конфигурации нет max_transient_retries")
    return stored


def _require_types(value: object, **fields: type | tuple[type, ...]) -> None:
    if not isinstance(value, dict):
        raise ValueError("ожидался JSON-объект")
    for name, kinds in fields.items():
        allowed = kinds if isinstance(kinds, tuple) else (kinds,)
        if type(value.get(name)) not in allowed:
            raise ValueError(f"неверный тип или отсутствует поле {name}")


def _load_attempt(path: Path) -> AttemptRecord:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        # Dataclass проверяет имена полей, но не их типы. Scorer ожидает строки формул.
        _require_types(
            data, slot_id=str, channel=str, model=str, status=str,
            initial_temperature=(int, float), repair_temperature=(int, float),
            max_transient_retries=int, extraction=dict, calls=list, errors=list,
            elapsed_seconds=(int, float),
        )
        if not math.isfinite(data["elapsed_seconds"]) or data["elapsed_seconds"] < 0:
            raise ValueError("неверное значение elapsed_seconds")
        extraction = data["extraction"]
        _require_types(
            extraction, benchmark_id=str, args=list, return_type=str,
            domain_constraints=list, postcondition=str, confidence=str, notes=str,
        )
        for field in ("args", "domain_constraints"):
            if any(not isinstance(item, str) for item in extraction[field]):
                raise ValueError(f"{field} должен содержать строки")
        _require_types(
            {"degraded": False, "degraded_reason": "", "extraction_trace": None, **extraction},
            degraded=bool, degraded_reason=str, extraction_trace=(dict, type(None)),
        )
        output_errors = set()
        for error in data["errors"]:
            _require_types(
                error, call_index=int, dispatch_index=int, category=str,
                error_type=str, message=str, status_code=(int, type(None)),
                response_body=(str, type(None)),
            )
            if error["category"] == "model_output_format":
                output_errors.add((error["call_index"], error["dispatch_index"]))
        for call in data["calls"]:
            _require_types(call, index=int, stage=str, temperature=(int, float), dispatch_count=int)
            dispatches = call["dispatch_count"]
            if not 1 <= dispatches <= data["max_transient_retries"] + 1:
                raise ValueError("неверное значение dispatch_count")
            # Без response допустима наблюдаемая ошибка формата последнего вызова.
            if not isinstance(call.get("response"), dict) and (
                call.get("response") is not None or (call["index"], dispatches) not in output_errors
            ):
                raise ValueError("нет response или подтверждённой ошибки формата")
        return AttemptRecord(
            slot_id=data["slot_id"],
            channel=data["channel"],
            model=data["model"],
            initial_temperature=data["initial_temperature"],
            repair_temperature=data["repair_temperature"],
            max_transient_retries=data["max_transient_retries"],
            status=data["status"],
            extraction=ExtractionResult(**extraction),
            calls=[LogicalCall(**call) for call in data["calls"]],
            errors=[AttemptError(**error) for error in data["errors"]],
            elapsed_seconds=data["elapsed_seconds"],
        )
    except (OSError, ValueError, KeyError, TypeError, OverflowError) as exc:
        raise PoolIntegrityError(f"Повреждённый candidate record {path}: {exc}") from exc


def _validate_record(
    record: AttemptRecord,
    *,
    case: BenchmarkCase,
    slot_id: str,
    channel: Channel,
    model: str,
    temperature: float,
    retries: int,
) -> None:
    if (
        record.slot_id != slot_id
        or record.channel != channel
        or record.model != model
        or record.initial_temperature != temperature
        or record.repair_temperature != 0.0
        or record.max_transient_retries != retries
        or record.status != "completed"
        or record.extraction.benchmark_id != case.benchmark_id
    ):
        raise PoolIntegrityError(f"Slot {slot_id}: metadata не совпадает")
    # Отдельный slot ID не доказывает вызов модели; в записи должны быть
    # наблюдаемые logical calls штатного extractor.
    if not record.calls or any(
        call.index != index
        or call.stage != ("initial" if index == 0 else "repair")
        or call.temperature != (temperature if index == 0 else 0.0)
        for index, call in enumerate(record.calls)
    ):
        raise PoolIntegrityError(f"Slot {slot_id}: нет достоверных logical calls")


def _result_path(directory: Path, slot_id: str) -> Path:
    return directory / slot_id.replace(":", "__") / "result.json"


def _write_json_atomically(path: Path, payload: object) -> None:
    temporary = path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    temporary.replace(path)


def run_candidate_pool(
    client: LLMClient,
    *,
    case: BenchmarkCase,
    artifact_dir: Path,
    model: str,
    provider: str,
    treatment_temperature: float,
    max_transient_retries: int = 0,
) -> list[AttemptRecord]:
    """Пять отдельных attempts на канал; completed slots повторно не генерируются."""
    specs = _slot_specs(case, treatment_temperature)
    if max_transient_retries < 0:
        raise ValueError("max_transient_retries must be nonnegative")
    endpoint = validate_sampling_client(client, model=model, live=provider != "fake")
    artifact_dir.mkdir(parents=True, exist_ok=True)
    _config(
        artifact_dir,
        case=case,
        model=model,
        provider=provider,
        temperature=treatment_temperature,
        retries=max_transient_retries,
        create=True,
        endpoint=endpoint,
    )

    records: list[AttemptRecord] = []
    for slot_id, channel, temperature in specs:
        path = _result_path(artifact_dir, slot_id)
        if path.exists():
            record = _load_attempt(path)
            _validate_record(
                record, case=case, slot_id=slot_id, channel=channel,
                model=model, temperature=temperature, retries=max_transient_retries,
            )
        else:
            # Исходный extractor выполняет полный validation/repair. При crash
            # без итогового result.json slot остаётся incomplete и будет перезапущен.
            record = run_extraction_attempt(
                client,
                slot_id=slot_id,
                channel=channel,
                case=case,
                model=model,
                initial_temperature=temperature,
                max_transient_retries=max_transient_retries,
            )
            path.parent.mkdir(parents=True, exist_ok=True)
            if record.status != "completed":
                # Диагностика последнего сбоя остаётся доступной и после resume.
                _write_json_atomically(path.with_name("failure.json"), asdict(record))
                return [*records, record]
            _write_json_atomically(path, asdict(record))
        records.append(record)
    return records


def verify_candidate_pool(
    *,
    artifact_dir: Path,
    case: BenchmarkCase,
    model: str,
    provider: str,
    treatment_temperature: float,
) -> list[AttemptRecord]:
    """Читает финальные candidates offline; НЕ воспроизводит генерацию через LLM."""
    specs = _slot_specs(case, treatment_temperature)
    config = _config(
        artifact_dir,
        case=case,
        model=model,
        provider=provider,
        temperature=treatment_temperature,
        retries=None,
        create=False,
    )
    expected = {slot_id for slot_id, _, _ in specs}
    loaded: dict[str, AttemptRecord] = {}
    paths: dict[str, Path] = {}
    for path in artifact_dir.glob("*/result.json"):
        record = _load_attempt(path)
        if record.slot_id in loaded:
            raise PoolIntegrityError(f"Повторный slot ID: {record.slot_id}")
        loaded[record.slot_id] = record
        paths[record.slot_id] = path

    if expected != set(loaded):
        missing = sorted(expected - set(loaded))
        incomplete = [
            slot_id for slot_id in missing
            if _result_path(artifact_dir, slot_id).with_name("failure.json").is_file()
        ]
        extra = sorted(set(loaded) - expected)
        raise PoolIntegrityError(
            f"Неверный набор slots: missing={missing}, incomplete={incomplete}, extra={extra}"
        )

    result: list[AttemptRecord] = []
    for slot_id, channel, temperature in specs:
        record = loaded[slot_id]
        if _result_path(artifact_dir, slot_id).resolve() != paths[slot_id].resolve():
            raise PoolIntegrityError(f"Slot {slot_id}: unexpected path")
        _validate_record(
            record, case=case, slot_id=slot_id, channel=channel,
            model=model, temperature=temperature,
            retries=config["max_transient_retries"],
        )
        result.append(record)
    return result
