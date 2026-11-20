"""Запуск одной полной extraction attempt для RQ1."""

from __future__ import annotations

import json
import re
import time
from copy import deepcopy
from dataclasses import dataclass
from typing import Literal

import requests

from dualify.ollama_client import LLMClient
from dualify.phases.p01_spec_to_logic import extract_spec_logic
from dualify.phases.p02_code_to_logic import extract_code_logic
from dualify.types import BenchmarkCase, ExtractionResult

Channel = Literal["spec", "code"]


@dataclass
class LogicalCall:
    index: int
    stage: Literal["initial", "repair"]
    temperature: float
    dispatch_count: int = 0
    response: dict | None = None


@dataclass(frozen=True)
class AttemptError:
    call_index: int
    dispatch_index: int
    category: str
    error_type: str
    message: str
    status_code: int | None = None
    response_body: str | None = None


@dataclass(frozen=True)
class AttemptRecord:
    slot_id: str
    channel: Channel
    model: str
    initial_temperature: float
    repair_temperature: float
    max_transient_retries: int
    status: str
    extraction: ExtractionResult
    calls: list[LogicalCall]
    errors: list[AttemptError]
    elapsed_seconds: float

    @property
    def logical_call_count(self) -> int:
        return len(self.calls)


class _AttemptClient:
    """Передаёт T>0 только в первый вызов, не вмешиваясь в native repair."""

    def __init__(
        self,
        inner: LLMClient,
        initial_temperature: float,
        max_transient_retries: int,
    ) -> None:
        self.inner = inner
        self.initial_temperature = initial_temperature
        self.max_transient_retries = max_transient_retries
        self.calls: list[LogicalCall] = []
        self.errors: list[AttemptError] = []
        self.terminal_category: str | None = None
        self._terminal_error: Exception | None = None

    def generate_json(self, prompt: str, temperature: float = 0.0) -> dict:
        stage: Literal["initial", "repair"] = "initial" if not self.calls else "repair"
        call_temperature = self.initial_temperature if stage == "initial" else 0.0
        call = LogicalCall(
            index=len(self.calls),
            stage=stage,
            temperature=call_temperature,
        )
        self.calls.append(call)

        # После терминального provider failure native extractor может запросить repair.
        # Не отправляем новые запросы: slot уже нельзя достоверно завершить.
        if self._terminal_error is not None:
            raise self._terminal_error

        # Считаем только видимые передачи в inner client. Его собственные HTTP
        # retries здесь не наблюдаем и не выдаём за физические provider requests.
        for dispatch_index in range(1, self.max_transient_retries + 2):
            call.dispatch_count += 1
            try:
                response = self.inner.generate_json(prompt, temperature=call_temperature)
                call.response = deepcopy(response)
                return response
            except Exception as exc:
                category, status_code = _classify_error(exc)
                self.errors.append(
                    AttemptError(
                        call_index=call.index,
                        dispatch_index=dispatch_index,
                        category=category,
                        error_type=type(exc).__name__,
                        message=_redact_credentials(str(exc)),
                        status_code=status_code,
                        response_body=_response_body(exc),
                    )
                )
                if category == "transient_infrastructure" and (
                    dispatch_index <= self.max_transient_retries
                ):
                    continue
                if category in {
                    "transient_infrastructure",
                    "permanent_config",
                    "ambiguous_provider_failure",
                }:
                    self.terminal_category = category
                    self._terminal_error = exc
                raise

        raise AssertionError("unreachable")

    def healthcheck(self) -> None:
        self.inner.healthcheck()


def run_extraction_attempt(
    client: LLMClient,
    *,
    slot_id: str,
    channel: Channel,
    case: BenchmarkCase,
    model: str,
    initial_temperature: float,
    max_transient_retries: int = 0,
) -> AttemptRecord:
    """Запускает один штатный p01/p02 extractor и записывает доступную телеметрию."""
    attempt_client = _AttemptClient(client, initial_temperature, max_transient_retries)
    started_at = time.perf_counter()

    if channel == "spec":
        extraction = extract_spec_logic(
            attempt_client,
            benchmark_id=case.benchmark_id,
            signature=case.signature,
            informal_spec=case.informal_spec,
            return_type=case.return_type,
            extra_context=case.extra_context,
            arg_types=case.arg_types,
        )
    else:
        extraction = extract_code_logic(
            attempt_client,
            benchmark_id=case.benchmark_id,
            signature=case.signature,
            function_source=case.function_source,
            return_type=case.return_type,
            extra_context=case.extra_context,
            arg_types=case.arg_types,
        )

    if attempt_client.terminal_category == "permanent_config":
        status = "permanent_config_failure"
    elif attempt_client.terminal_category is not None:
        status = "incomplete"
    else:
        status = "completed"

    return AttemptRecord(
        slot_id=slot_id,
        channel=channel,
        model=model,
        initial_temperature=initial_temperature,
        repair_temperature=0.0,
        max_transient_retries=max_transient_retries,
        status=status,
        extraction=extraction,
        calls=attempt_client.calls,
        errors=attempt_client.errors,
        elapsed_seconds=time.perf_counter() - started_at,
    )


def _classify_error(exc: Exception) -> tuple[str, int | None]:
    """Классифицирует только причины, которые можно установить по исключению."""
    if isinstance(exc, requests.HTTPError) and exc.response is not None:
        status_code = exc.response.status_code
        body = exc.response.text.lower()
        if status_code in {401, 403, 404, 405}:
            return "permanent_config", status_code
        if status_code == 429 or status_code >= 500:
            return "transient_infrastructure", status_code
        if status_code in {400, 422}:
            output_markers = (
                "failed_generation",
                "generated json",
                "generated output",
                "model output",
                "model response",
            )
            if any(marker in body for marker in output_markers):
                return "model_output_format", status_code
            request_validation = "request" in body and any(
                marker in body for marker in ("schema", "validation", "required")
            )
            model_config = "model" in body and any(
                marker in body for marker in ("required", "unsupported", "not found")
            )
            if request_validation or model_config:
                return "permanent_config", status_code
        if 400 <= status_code < 500:
            return "ambiguous_provider_failure", status_code
    if isinstance(exc, (requests.ConnectionError, requests.Timeout)):
        return "transient_infrastructure", None
    if isinstance(exc, requests.RequestException):
        return "ambiguous_provider_failure", None
    if isinstance(exc, json.JSONDecodeError):
        return "model_output_format", None
    return "ambiguous_provider_failure", None


def _response_body(exc: Exception) -> str | None:
    if isinstance(exc, requests.HTTPError) and exc.response is not None:
        return _redact_credentials(exc.response.text)[:500]
    return None


def _redact_credentials(text: str) -> str:
    text = re.sub(
        r"(?i)(bearer\s+)[^\s,;\"'}]+",
        r"\1[REDACTED]",
        text,
    )
    return re.sub(
        r"(?i)((?:api[_-]?key|access[_-]?token|token)[\"']?\s*[:=]\s*[\"']?)"
        r"[^\"'\s&,}]+",
        r"\1[REDACTED]",
        text,
    )
