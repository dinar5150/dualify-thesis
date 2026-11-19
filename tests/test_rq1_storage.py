import json

import pytest
import requests

from dualify.ollama_client import OpenAICompatibleClient
from dualify.rq1 import ExperimentConfig, ExperimentPlan
from dualify.rq1_storage import execute, slot_key
from dualify.types import BenchmarkCase


class FakeClient:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = 0
        self.api_key = 'secret-key'

    def healthcheck(self):
        pass

    def generate_json(self, prompt, temperature=0.0):
        self.calls += 1
        result = next(self.responses)
        if isinstance(result, BaseException):
            raise result
        return result


def payload():
    return {'args': ['x'], 'return_type': 'int', 'domain_constraints': [],
            'postcondition': 'ret == x + 1', 'confidence': 'high', 'notes': ''}


def make_plan(samples=1):
    case = BenchmarkCase('demo', 'demo.py', 'demo', 1, 'demo(x: int) -> int',
                         {'x': 'int'}, 'int', 'Add one.', '',
                         'def demo(x: int) -> int:\n    return x + 1')
    return ExperimentPlan({'qualified': case}, ExperimentConfig(samples=samples))


def read_result(directory, channel, index):
    path = directory / 'attempts' / slot_key('qualified', channel, index) / 'result.json'
    return json.loads(path.read_text())


def test_completed_immediate_and_resume_no_duplicate(tmp_path):
    plan = make_plan(2)
    fake = FakeClient([payload()] * 4)
    first = execute(plan, fake, tmp_path, {'model': 'x'}, max_new_attempts=1)
    assert first['completed'] == 1 and fake.calls == 1
    assert read_result(tmp_path, 'spec', 0)['data']['final_extraction']['postcondition']
    with pytest.raises(ValueError, match='not empty'):
        execute(plan, fake, tmp_path, {'model': 'x'})
    second = execute(plan, fake, tmp_path, {'model': 'x'}, resume=True)
    assert second['completed'] == 4 and second['new_attempts'] == 3
    assert fake.calls == 4
    assert execute(plan, fake, tmp_path, {'model': 'x'}, resume=True)['new_attempts'] == 0
    assert len(list(tmp_path.glob('attempts/*/result.json'))) == 4
    assert not any('secret-key' in path.read_text() for path in tmp_path.rglob('*.json'))


def test_interruption_leaves_marker_and_resumes(tmp_path):
    plan = make_plan()
    with pytest.raises(KeyboardInterrupt):
        execute(plan, FakeClient([KeyboardInterrupt()]), tmp_path, {})
    slot = tmp_path / 'attempts' / slot_key('qualified', 'spec', 0)
    assert len(list(slot.glob('started-*.json'))) == 1
    assert not (slot / 'result.json').exists()
    result = execute(plan, FakeClient([payload(), payload()]), tmp_path, {}, resume=True)
    assert result['completed'] == 2
    assert len(list(slot.glob('started-*.json'))) == 2


def test_failed_generation_is_terminal_and_not_replayed(tmp_path):
    plan = make_plan()
    fake = FakeClient([RuntimeError('bad secret-key')] * 3 + [payload()])
    result = execute(plan, fake, tmp_path, {})
    assert result['completed'] == 2 and result['errors'] == 1
    record = read_result(tmp_path, 'spec', 0)
    assert record['status'] == 'error'
    assert '[REDACTED]' in record['data']['errors'][0]
    assert record['data']['diagnostics']['request_count'] == 3
    assert execute(plan, FakeClient([]), tmp_path, {}, resume=True)['errors'] == 1


def test_rejects_configuration_and_corrupt_records(tmp_path):
    plan = make_plan()
    execute(plan, FakeClient([payload()]), tmp_path, {'model': 'x'}, max_new_attempts=1)
    with pytest.raises(ValueError, match='configuration differs'):
        execute(plan, FakeClient([]), tmp_path, {'model': 'y'}, resume=True)
    path = tmp_path / 'attempts' / slot_key('qualified', 'spec', 0) / 'result.json'
    path.write_text('{')
    with pytest.raises(ValueError, match='Corrupt record'):
        execute(plan, FakeClient([]), tmp_path, {'model': 'x'}, resume=True)


def test_detects_tampering_and_partial_files(tmp_path):
    plan = make_plan()
    execute(plan, FakeClient([payload()]), tmp_path, {}, max_new_attempts=1)
    slot = tmp_path / 'attempts' / slot_key('qualified', 'spec', 0)
    result_path = slot / 'result.json'
    result = json.loads(result_path.read_text())
    result['data']['status'] = 'error'
    result_path.write_text(json.dumps(result))
    with pytest.raises(ValueError, match='Corrupt completed result'):
        execute(plan, FakeClient([]), tmp_path, {}, resume=True)
    result_path.unlink()
    (slot / '.partial.tmp').write_text('{')
    with pytest.raises(ValueError, match='incomplete file'):
        execute(plan, FakeClient([]), tmp_path, {}, resume=True)


def test_eight_distinct_terminal_slots_per_channel(tmp_path):
    plan = make_plan(8)
    result = execute(plan, FakeClient([payload()] * 16), tmp_path, {})
    assert result['completed'] == 16
    records = [json.loads(path.read_text()) for path in tmp_path.glob('attempts/*/result.json')]
    assert {(record['channel'], record['sample_index']) for record in records} == {
        (channel, index) for channel in ('spec', 'code') for index in range(8)}


def test_http_429_retry_and_usage_instrumentation(tmp_path, monkeypatch):
    calls = []

    def post(url, **kwargs):
        calls.append((url, kwargs['json']['temperature']))
        response = requests.Response()
        response.status_code = 429 if len(calls) == 1 else 200
        response._content = json.dumps({
            'choices': [{'message': {'content': json.dumps(payload())}}],
            'usage': {'prompt_tokens': 10, 'completion_tokens': 2},
        }).encode()
        response.url = url
        return response

    monkeypatch.setenv('DUALIFY_OPENAI_USE_CHAT', '1')
    monkeypatch.setattr(requests, 'post', post)
    client = OpenAICompatibleClient('test', 'https://api.groq.com/openai', 'secret',
                                    max_retries=2, backoff_base_sec=0, max_backoff_sec=0)
    monkeypatch.setattr(client, 'healthcheck', lambda: None)
    result = execute(make_plan(), client, tmp_path, {})
    assert result['completed'] == 2
    metrics = read_result(tmp_path, 'spec', 0)['data']['diagnostics']
    assert metrics['request_count'] == 1 and metrics['http_request_count'] == 2
    assert metrics['http_429_count'] == 1 and metrics['retry_count'] == 1
    assert metrics['rate_limit_wait_seconds'] >= 0
    assert metrics['token_usage'] == [{'prompt_tokens': 10, 'completion_tokens': 2}]
    assert all('/v1/chat/completions' in url for url, _ in calls)
    assert all(temperature == 0.7 for _, temperature in calls)


def test_cli_writes_manifest_and_resumes_without_repeating(tmp_path, monkeypatch, capsys):
    import runpy
    import sys
    from pathlib import Path

    import dualify.ollama_client

    root = Path(__file__).resolve().parents[1]
    script = root / 'scripts/run_rq1.py'
    output = tmp_path / 'run'
    fake = FakeClient([payload()] * 12)
    monkeypatch.setattr(dualify.ollama_client, 'create_llm_client', lambda **kwargs: fake)
    monkeypatch.setenv('GROQ_API_KEY', 'secret-key')
    monkeypatch.setenv('DUALIFY_OPENAI_USE_CHAT', '1')
    argv = [str(script), '--run', '--dev', '--samples', '1', '--output-dir', str(output),
            '--max-new-attempts', '1', '--inter-request-seconds', '0']
    monkeypatch.setattr(sys, 'argv', argv)
    with pytest.raises(SystemExit) as first:
        runpy.run_path(str(script), run_name='__main__')
    assert first.value.code == 0
    assert json.loads(capsys.readouterr().out)['new_attempts'] == 1
    manifest = json.loads((output / 'manifest.json').read_text())
    assert len(manifest['configuration']['selected_case_ids']) == 6
    assert manifest['configuration']['openai_use_chat'] == '1'
    assert 'secret-key' not in (output / 'manifest.json').read_text()
    monkeypatch.setattr(sys, 'argv', [*argv, '--resume'])
    with pytest.raises(SystemExit) as second:
        runpy.run_path(str(script), run_name='__main__')
    assert second.value.code == 0
    assert json.loads(capsys.readouterr().out)['completed'] == 2
