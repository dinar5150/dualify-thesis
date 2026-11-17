from pathlib import Path

import pytest

from dualify import rq1
from dualify.phases.p01_spec_to_logic import extract_spec_logic
from dualify.phases.p02_code_to_logic import extract_code_logic
from dualify.types import BenchmarkCase, ExtractionResult

ROOT = Path(__file__).resolve().parents[1]


class FakeClient:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = []

    def healthcheck(self):
        pass

    def generate_json(self, prompt, temperature=0.0):
        self.calls.append((prompt, temperature))
        response = next(self.responses)
        if isinstance(response, Exception):
            raise response
        return response


def payload(post='ret == x + 1'):
    return {'args': ['x'], 'return_type': 'int', 'domain_constraints': [],
            'postcondition': post, 'confidence': 'high', 'notes': ''}


def simple_case(return_type='int'):
    return BenchmarkCase('demo', 'demo.py', 'demo', 1, f'demo(x: int) -> {return_type}',
                         {'x': 'int'}, return_type, 'Add one.', '',
                         'def demo(x: int) -> int:\n    return x + 1')


def plan(case, samples=1):
    return rq1.ExperimentPlan({'qualified': case}, rq1.ExperimentConfig(samples=samples))


@pytest.mark.parametrize('channel', ['spec', 'code'])
def test_original_prompts_and_temperature(channel):
    case = simple_case()
    invalid = payload('unknown_name == 1')
    response = payload()
    baseline = FakeClient([invalid, response])
    kwargs = dict(client=baseline, benchmark_id=case.benchmark_id, signature=case.signature,
                  return_type=case.return_type, arg_types=case.arg_types,
                  extra_context=case.extra_context)
    if channel == 'spec':
        extract_spec_logic(informal_spec=case.informal_spec, **kwargs)
    else:
        extract_code_logic(function_source=case.function_source, **kwargs)
    assert [temp for _, temp in baseline.calls] == [0.0, 0.0]
    fake = FakeClient([invalid, response, invalid, response])
    results = list(rq1.sample_plan(plan(case), fake))
    candidate = next(c for c in results if c.channel == channel)
    calls = fake.calls[:2] if channel == 'spec' else fake.calls[2:]
    assert [prompt for prompt, _ in calls] == [prompt for prompt, _ in baseline.calls]
    assert [temp for _, temp in calls] == [0.7, 0.0]
    assert candidate.stage_trace['initial']['errors']
    assert candidate.stage_trace['repair']['errors'] == []
    assert candidate.final_extraction.postcondition == 'ret == x + 1'


def test_slots_independent_and_no_action_or_gold():
    case = simple_case()
    fake = FakeClient([payload('ret == x + 1'), payload('ret == x + 2'),
                       payload('ret == x + 3'), payload('ret == x + 4')])
    candidates = list(rq1.sample_plan(plan(case, 2), fake))
    assert [(c.channel, c.sample_index) for c in candidates] == [
        ('spec', 0), ('spec', 1), ('code', 0), ('code', 1)]
    assert len(fake.calls) == 4
    assert len({c.final_extraction.postcondition for c in candidates}) == 4
    assert fake.calls[0][0] == fake.calls[1][0]
    assert fake.calls[2][0] == fake.calls[3][0]
    assert all('ret == x + 1' not in prompt for prompt, _ in fake.calls)
    assert all('gold' not in prompt.lower() for prompt, _ in fake.calls)


def test_six_dev_cases_with_fake_clients():
    class FlexibleFake:
        def __init__(self):
            self.calls = []

        def healthcheck(self):
            pass

        def generate_json(self, prompt, temperature=0.0):
            self.calls.append(prompt)
            return {'args': [], 'postcondition': 'ret == ret', 'domain_constraints': []}

    fake = FlexibleFake()
    candidates = list(rq1.sample_plan(rq1.make_plan(ROOT, rq1.ExperimentConfig(samples=1),
                                                    dev=True), fake))
    assert len(candidates) == 12
    assert len({c.case_id for c in candidates}) == 6
    assert all('gold' not in p.lower() for p in fake.calls)
    assert all('action plan' not in p.lower() for p in fake.calls)


def test_runner_normalization_and_fallback(monkeypatch):
    case = simple_case('bool')
    original = ExtractionResult('demo', ['x'], 'bool', [], 'x > 0', 'high', '')
    fallback = ExtractionResult('demo', ['x'], 'bool', [], 'ret == True', 'fallback', '')
    calls = []

    def spec(**kwargs):
        calls.append('spec')
        return original

    def code(**kwargs):
        calls.append('code')
        return original

    monkeypatch.setattr(rq1, 'extract_spec_logic', spec)
    monkeypatch.setattr(rq1, 'extract_code_logic', code)
    monkeypatch.setattr(rq1, 'is_parseable', lambda *args: False)
    monkeypatch.setattr(rq1, 'get_fallback_extraction', lambda _: fallback)
    candidates = list(rq1.sample_plan(plan(case, 2), FakeClient([])))
    assert calls == ['spec', 'spec', 'code', 'code']
    assert all(c.extraction_before_fallback.postcondition == 'ret == (x > 0)' for c in candidates)
    assert all(c.used_fallback and c.final_extraction == fallback for c in candidates)


def test_original_caught_llm_error_is_reported():
    fake = FakeClient([RuntimeError('API failed'), payload(), payload()])
    result = list(rq1.sample_plan(plan(simple_case()), fake))
    assert result[0].status == 'error'
    assert 'API failed' in result[0].errors[0]
