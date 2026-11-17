"""Durable, resumable RQ1 sampling, with external provider instrumentation."""
from __future__ import annotations

import fcntl
import hashlib
import json
import math
import os
import time
import uuid
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest.mock import patch

import requests

from dualify.ollama_client import LLMClient, OpenAICompatibleClient
from dualify.rq1 import ExperimentPlan, sample_plan


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _encoded(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()


def _digest(value: Any) -> str:
    return hashlib.sha256(_encoded(value)).hexdigest()


def _redact(value: Any, secret: str) -> Any:
    if not secret:
        return value
    if isinstance(value, str):
        return value.replace(secret, '[REDACTED]')
    if isinstance(value, list):
        return [_redact(item, secret) for item in value]
    if isinstance(value, dict):
        return {_redact(key, secret): _redact(item, secret) for key, item in value.items()}
    return value


def slot_key(case_id: str, channel: str, index: int) -> str:
    return _digest([case_id, channel, index])


def _write_new(path: Path, payload: dict[str, Any]) -> None:
    """Atomically publish a new file without replacing an existing result."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.parent / f'.{uuid.uuid4().hex}.tmp'
    try:
        with temp.open('xb') as stream:
            stream.write(_encoded(payload) + b'\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temp, path)
        descriptor = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    finally:
        temp.unlink(missing_ok=True)


def _read(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding='utf-8'))
        if not isinstance(value, dict):
            raise ValueError('not an object')
        return value
    except (ValueError, OSError, UnicodeError) as exc:
        raise ValueError(f'Corrupt record {path}: {exc}') from exc


class DiagnosticClient:
    """Observe original HTTP calls and retries without changing their behavior.

    HTTP instrumentation is scoped to a single synchronous call; the runner
    holds an exclusive process lock and is intended for single-threaded use.
    """
    def __init__(self, inner: LLMClient, interval: float) -> None:
        self.inner = inner
        self.interval = interval
        self.last_call: float | None = None
        self.reset()

    def reset(self) -> None:
        observed = isinstance(self.inner, OpenAICompatibleClient)
        self.metrics: dict[str, Any] = {
            'request_count': 0, 'http_request_count': 0 if observed else None,
            'http_429_count': 0 if observed else None, 'retry_count': 0 if observed else None,
            'rate_limit_wait_seconds': 0.0 if observed else None,
            'provider_failures': [], 'token_usage': [],
        }

    def healthcheck(self) -> None:
        self.inner.healthcheck()

    def generate_json(self, prompt: str, temperature: float = 0.0) -> dict:
        if self.last_call is not None:
            delay = self.interval - (time.monotonic() - self.last_call)
            if delay > 0:
                time.sleep(delay)
        self.last_call = time.monotonic()
        self.metrics['request_count'] += 1
        if not isinstance(self.inner, OpenAICompatibleClient):
            return self.inner.generate_json(prompt, temperature=temperature)
        client = self.inner
        original_post = requests.post
        original_sleep = time.sleep
        original_retry = client._post_with_retry
        last_status: int | None = None
        posts_in_retry = 0

        def observed_post(*args: Any, **kwargs: Any) -> requests.Response:
            nonlocal last_status, posts_in_retry
            self.metrics['http_request_count'] += 1
            posts_in_retry += 1
            last_status = None
            try:
                response = original_post(*args, **kwargs)
            except requests.RequestException as exc:
                self.metrics['provider_failures'].append({'type': type(exc).__name__})
                raise
            last_status = response.status_code
            if response.status_code == 429:
                self.metrics['http_429_count'] += 1
            if response.status_code >= 400:
                self.metrics['provider_failures'].append({'http_status': response.status_code})
            if response.ok:
                try:
                    body = response.json()
                    if isinstance(body, dict) and isinstance(body.get('usage'), dict):
                        self.metrics['token_usage'].append(body['usage'])
                except (ValueError, TypeError):
                    pass
            return response

        def observed_sleep(seconds: float) -> None:
            start = time.monotonic()
            try:
                original_sleep(seconds)
            finally:
                if last_status == 429:
                    self.metrics['rate_limit_wait_seconds'] += time.monotonic() - start

        def observed_retry(url: str, payload: dict) -> requests.Response:
            nonlocal posts_in_retry
            posts_in_retry = 0
            try:
                return original_retry(url, payload)
            finally:
                self.metrics['retry_count'] += max(0, posts_in_retry - 1)

        with (patch.object(requests, 'post', observed_post),
              patch.object(time, 'sleep', observed_sleep),
              patch.object(client, '_post_with_retry', observed_retry)):
            return client.generate_json(prompt, temperature=temperature)


def _slots(plan: ExperimentPlan) -> dict[str, tuple[str, str, int, str]]:
    return {slot_key(identifier, channel, index): (identifier, channel, index, case.benchmark_id)
            for identifier, case in plan.cases.items() for channel in ('spec', 'code')
            for index in range(plan.config.samples)}


def execute(plan: ExperimentPlan, client: LLMClient, output_dir: Path,
            configuration: dict[str, Any], *, resume: bool = False,
            max_new_attempts: int | None = None, interval: float = 0.0) -> dict[str, Any]:
    if max_new_attempts is not None and max_new_attempts < 1:
        raise ValueError('max-new-attempts must be positive')
    if not math.isfinite(interval) or interval < 0:
        raise ValueError('inter-request-seconds must be nonnegative')
    plan_settings = {'case_ids': list(plan.cases), 'samples': plan.config.samples,
                     'model': plan.config.model, 'temperature': plan.config.temperature,
                     'inter_request_seconds': interval}
    output_dir.mkdir(parents=True, exist_ok=True)
    with (output_dir / '.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        manifest_path = output_dir / 'manifest.json'
        if resume:
            if not manifest_path.exists():
                raise ValueError('Cannot resume: manifest.json does not exist')
            manifest = _read(manifest_path)
            if (manifest.get('schema_version') != 1 or
                    not isinstance(manifest.get('experiment_id'), str) or
                    not manifest.get('started_at')):
                raise ValueError('Corrupt manifest: missing experiment identity or start time')
            if manifest.get('configuration') != configuration:
                raise ValueError('Cannot resume: experiment configuration differs from manifest')
            if manifest.get('plan') != plan_settings:
                raise ValueError('Cannot resume: plan configuration differs from manifest')
        else:
            if any(p.name != '.lock' for p in output_dir.iterdir()):
                raise ValueError('Output directory is not empty; use --resume or a new directory')
            manifest = {'schema_version': 1, 'experiment_id': uuid.uuid4().hex,
                        'started_at': utc_now(), 'configuration': configuration,
                        'plan': plan_settings}
            _write_new(manifest_path, manifest)
        experiment_id = manifest['experiment_id']
        slots = _slots(plan)
        attempts_dir = output_dir / 'attempts'
        if attempts_dir.exists() and not attempts_dir.is_dir():
            raise ValueError('Corrupt output: attempts is not a directory')
        completed: set[str] = set()
        failures = 0
        if attempts_dir.exists():
            for slot_dir in attempts_dir.iterdir():
                if not slot_dir.is_dir() or slot_dir.name not in slots:
                    raise ValueError(f'Unexpected or corrupt slot: {slot_dir}')
                identifier, channel, index, benchmark_id = slots[slot_dir.name]
                for path in slot_dir.iterdir():
                    if not (path.name == 'result.json' or
                            (path.name.startswith('started-') and path.suffix == '.json')):
                        raise ValueError(f'Unexpected or incomplete file: {path}')
                    record = _read(path)
                    expected = {'experiment_id': experiment_id, 'case_id': identifier,
                                'channel': channel, 'sample_index': index,
                                'benchmark_id': benchmark_id}
                    if any(record.get(k) != v for k, v in expected.items()):
                        raise ValueError(f'Corrupt identity in {path}')
                    if path.name == 'result.json':
                        if (record.get('status') not in ('completed', 'error') or
                                record.get('checksum') != _digest(record.get('data'))):
                            raise ValueError(f'Corrupt completed result: {path}')
                        data = record.get('data')
                        if (not isinstance(data, dict) or
                                any(data.get(k) != v for k, v in expected.items()
                                    if k != 'experiment_id') or
                                data.get('status') != record['status']):
                            raise ValueError(f'Corrupt result content: {path}')
                        attempt_id = record.get('attempt_id')
                        if (not isinstance(attempt_id, str) or not attempt_id.isalnum() or
                                not (slot_dir / f'started-{attempt_id}.json').is_file()):
                            raise ValueError(f'Missing started record for {path}')
                        completed.add(slot_dir.name)
                        failures += int(record['status'] == 'error')
                    elif (record.get('status') != 'running' or not record.get('started_at') or
                          path.name != f"started-{record.get('attempt_id')}.json"):
                        raise ValueError(f'Corrupt incomplete attempt: {path}')
        pending = len(slots) - len(completed)
        if not pending:
            return {'experiment_id': experiment_id, 'completed': len(completed),
                    'planned': len(slots), 'new_attempts': 0, 'errors': failures}
        client.healthcheck()
        observed = DiagnosticClient(client, interval)
        started = 0
        current: dict[str, Any] = {}

        def should_run(identifier: str, channel: str, index: int) -> bool:
            nonlocal started, current
            key = slot_key(identifier, channel, index)
            if key in completed or (max_new_attempts is not None and started >= max_new_attempts):
                return False
            observed.reset()
            attempt_id = uuid.uuid4().hex
            current = {'experiment_id': experiment_id, 'case_id': identifier, 'channel': channel,
                       'sample_index': index, 'benchmark_id': slots[key][3],
                       'attempt_id': attempt_id, 'status': 'running', 'started_at': utc_now()}
            _write_new(attempts_dir / key / f'started-{attempt_id}.json', current)
            current['started_monotonic'] = time.monotonic()
            started += 1
            return True

        for candidate in sample_plan(plan, observed, should_run=should_run):
            key = slot_key(candidate.case_id, candidate.channel, candidate.sample_index)
            # Do not serialize the configured secret even if an error or response echoes it.
            data = _redact(asdict(candidate), getattr(client, 'api_key', ''))
            data['diagnostics'] = dict(observed.metrics)
            data['duration_seconds'] = time.monotonic() - current['started_monotonic']
            data['finished_at'] = utc_now()
            result = {key_: value for key_, value in current.items() if key_ != 'started_monotonic'}
            result.update(status=candidate.status, data=data, checksum=_digest(data))
            _write_new(attempts_dir / key / 'result.json', result)
            completed.add(key)
            failures += int(candidate.status == 'error')
        return {'experiment_id': experiment_id, 'completed': len(completed),
                'planned': len(slots), 'new_attempts': started, 'errors': failures}
