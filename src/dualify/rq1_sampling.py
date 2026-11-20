"""Dev-only four-candidate acquisition using original Dualify extraction + repair."""

from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import requests

from dualify.discovery import discover_python_cases
from dualify.fallbacks import get_fallback_extraction
from dualify.ollama_client import LLMClient, create_llm_client
from dualify.phases.p01_spec_to_logic import extract_spec_logic
from dualify.phases.p02_code_to_logic import extract_code_logic
from dualify.phases.p03_smt_checking import CaseSpec, is_parseable
from dualify.rq1_dataset import validate_manifest
from dualify.runner import _normalize_extraction
from dualify.transcript import (
    RecordingLLMClient,
    ReplayLLMClient,
    ResumingLLMClient,
    TranscriptError,
)
from dualify.types import BenchmarkCase, ExtractionResult


def _dump(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n")
    temporary.replace(path)


def classify_error(exc: Exception) -> str:
    response = getattr(exc, "response", None)
    status = getattr(response, "status_code", None)
    body = getattr(response, "text", "") or ""
    if status in (400, 422) and any(
        marker in str(body).lower()
        for marker in ("json_validate_failed", "failed to generate json", "json validation")
    ):
        return "model_format"
    if status in (401, 403, 404, 400, 422):
        return "fatal_config"
    if status == 429 or (isinstance(status, int) and 500 <= status < 600):
        return "infrastructure"
    if isinstance(exc, (requests.Timeout, requests.ConnectionError)):
        return "infrastructure"
    # Unrecognized transport/format failures are not free redraws.
    return "ambiguous"


@dataclass
class AttemptClient:
    inner: LLMClient
    initial_temperature: float
    expected_temperatures: list[float] | None = None
    calls: list[dict[str, Any]] = field(default_factory=list)
    errors: list[dict[str, str]] = field(default_factory=list)
    poisoned: bool = False
    fatal: bool = False

    def generate_json(self, prompt: str, temperature: float = 0.0) -> dict:
        index = len(self.calls)
        target_t = self.initial_temperature if index == 0 else temperature
        if self.expected_temperatures is not None:
            if index >= len(self.expected_temperatures) or target_t != self.expected_temperatures[index]:
                self.poisoned = True
                raise TranscriptError("Unexpected replay call or temperature")
        entry: dict[str, Any] = {
            "index": index,
            "temperature": target_t,
            "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
            "state": "started",
        }
        self.calls.append(entry)
        if self.poisoned:
            entry["state"] = "blocked_after_failure"
            raise RuntimeError("Previous transport/replay error tainted this slot")
        try:
            response = self.inner.generate_json(prompt, temperature=target_t)
        except Exception as exc:
            category = classify_error(exc)
            entry["state"] = category
            self.errors.append({"category": category, "message": str(exc)[:500]})
            if category in ("infrastructure", "fatal_config", "ambiguous"):
                self.poisoned = True
            if category == "fatal_config":
                self.fatal = True
            raise
        entry["state"] = "ok"
        return response

    def healthcheck(self) -> None:
        self.inner.healthcheck()


def _load_transcript_temperatures(path: Path) -> list[float]:
    rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    records = [row for row in rows if "transcript_metadata" not in row]
    if not rows or "transcript_metadata" not in rows[0]:
        raise TranscriptError("Missing canonical transcript metadata")
    for i, record in enumerate(records):
        if record.get("call_index") != i or "temperature" not in record:
            raise TranscriptError(f"Invalid transcript index/temperature at {i}")
    return [float(record["temperature"]) for record in records]


def _extract(client: LLMClient, case: BenchmarkCase, channel: str) -> ExtractionResult:
    identity = Path(case.file).stem
    if channel == "spec":
        extracted = extract_spec_logic(
            client=client,
            benchmark_id=identity,
            signature=case.signature,
            informal_spec=case.informal_spec,
            return_type=case.return_type,
            extra_context=case.extra_context,
            arg_types=case.arg_types,
        )
    elif channel == "code":
        extracted = extract_code_logic(
            client=client,
            benchmark_id=identity,
            signature=case.signature,
            function_source=case.function_source,
            return_type=case.return_type,
            extra_context=case.extra_context,
            arg_types=case.arg_types,
        )
    else:
        raise ValueError(f"Unknown channel {channel}")
    case_spec = CaseSpec(
        benchmark_id=identity, arg_types=case.arg_types, return_type=case.return_type
    )
    extracted = ExtractionResult(
        **_normalize_extraction(case_spec, extracted.postcondition, asdict(extracted))
    )
    if not is_parseable(case_spec, extracted):
        try:
            extracted = get_fallback_extraction(identity)
        except ValueError:
            pass
    return extracted


def replay_attempt(case: BenchmarkCase, channel: str, transcript: Path, initial_t: float) -> dict[str, Any]:
    expected = _load_transcript_temperatures(transcript)
    replay = ReplayLLMClient.from_path(transcript, strict_prompts=True, match_by_prompt=False)
    wrapper = AttemptClient(replay, initial_t, expected_temperatures=expected)
    result = _extract(wrapper, case, channel)
    if wrapper.errors or replay.remaining_calls() or len(wrapper.calls) != len(expected):
        raise TranscriptError("Replay incomplete, divergent, or exhausted")
    return asdict(result)


def attempt(
    *,
    client: LLMClient,
    case: BenchmarkCase,
    channel: str,
    arm: str,
    index: int,
    temperature: float,
    run_dir: Path,
) -> dict[str, Any]:
    case_id = Path(case.file).stem
    slot = run_dir / "slots" / case_id / channel / f"{arm}-{index}"
    output, transcript = slot.with_suffix(".json"), slot.with_suffix(".jsonl")
    if output.exists():
        previous = json.loads(output.read_text())
        if previous.get("status") == "complete":
            if previous["extraction"] != replay_attempt(case, channel, transcript, temperature):
                raise TranscriptError(f"Previously completed slot has diverged: {slot}")
            return previous
        if previous.get("status") == "fatal_config":
            raise RuntimeError(f"Fatal configuration needs an explicit fix: {slot}")
    expected = _load_transcript_temperatures(transcript) if transcript.exists() else []
    if expected and (expected[0] != temperature or any(t != 0.0 for t in expected[1:])):
        raise TranscriptError("Previously recorded slot has incompatible temperatures")
    if transcript.exists():
        recorder: RecordingLLMClient | ResumingLLMClient = ResumingLLMClient.from_path(
            client, transcript, strict_prompts=True
        )
    else:
        recorder = RecordingLLMClient(
            client, transcript, model="recorded-in-locked-config", base_url="",
            provider="groq",
        )
    wrapper = AttemptClient(recorder, temperature, expected_temperatures=None)
    start = time.perf_counter()
    try:
        extraction = _extract(wrapper, case, channel)
    finally:
        recorder.close()
    elapsed = time.perf_counter() - start
    errors = wrapper.errors
    status = "fatal_config" if wrapper.fatal else "incomplete" if wrapper.poisoned else "complete"
    # Failed model-format calls stay inside the original repair ladder and are not redrawn.
    payload = {
        "slot": {"benchmark_id": case_id, "channel": channel, "arm": arm, "index": index},
        "status": status,
        "extraction": asdict(extraction),
        "elapsed_seconds": elapsed,
        "logical_calls": len(wrapper.calls),
        "calls": wrapper.calls,
        "errors": errors,
        "transcript_sha256": hashlib.sha256(transcript.read_bytes()).hexdigest(),
        "transport_http_attempts": None,
        "provider_inference_seconds": None,
    }
    _dump(output, payload)
    if status == "complete":
        if replay_attempt(case, channel, transcript, temperature) != payload["extraction"]:
            raise TranscriptError(f"Recorded slot failed strict replay: {slot}")
    elif status == "fatal_config":
        raise RuntimeError(f"Unusable provider/model configuration: {slot}")
    else:
        raise RuntimeError(f"Incomplete attempt slot; resume only this slot: {slot}")
    return payload


def collect_dev(
    *,
    root: Path,
    manifest_path: Path,
    run_dir: Path,
    model: str,
    temperature: float,
    api_key: str | None = None,
    base_url: str = "https://api.groq.com/openai",
) -> dict[str, Any]:
    if not 0 < temperature <= 2:
        raise ValueError("Frozen positive temperature must be in (0,2]")
    if not model or "/" not in model:
        raise ValueError("Provide exact Groq model ID (not just Qwen family)")
    key = api_key or os.environ.get("GROQ_API_KEY", "")
    if not key:
        raise RuntimeError("GROQ_API_KEY is unavailable; no live dev experiment was started")
    manifest = json.loads(manifest_path.read_text())
    validate_manifest(root, manifest)
    config = {
        "schema": "rq1-dev-v1",
        "model": model, "temperature": temperature, "base_url": base_url,
        "upstream_sha": manifest["upstream_sha"], "seed": manifest["seed"],
        "split_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
        "timeout_policy": "native Dualify Groq profile",
        "scope": "dev-only",
    }
    config_path = run_dir / "config.json"
    if config_path.exists() and json.loads(config_path.read_text()) != config:
        raise ValueError("Locked config mismatch: refuse changing model/temperature/split")
    if not config_path.exists():
        _dump(config_path, config)
    live = create_llm_client(provider="openai", model=model, base_url=base_url, api_key=key)
    live.healthcheck()
    available = {
        Path(case.file).stem: case
        for case in discover_python_cases(root / "benchmark" / "lifted_auto_eval", root)
    }
    started = time.perf_counter()
    completed = 0
    for case_id in manifest["dev"]:
        case = available[case_id]
        for channel in ("spec", "code"):
            for arm, count, t in (("baseline", 1, 0.0), ("sampling", 4, temperature)):
                for i in range(count):
                    attempt(
                        client=live, case=case, channel=channel, arm=arm, index=i,
                        temperature=t, run_dir=run_dir,
                    )
                    completed += 1
    result = {
        "scope": "dev-only",
        "status": "complete",
        "completed_slots": completed,
        "expected_slots": 100,
        "wall_seconds": time.perf_counter() - started,
    }
    _dump(run_dir / "collection.json", result)
    return result
