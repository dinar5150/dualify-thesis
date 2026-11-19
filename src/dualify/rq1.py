"""Configuration and case selection for the RQ1 experiment."""
from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal

from dualify.discovery import discover_python_cases
from dualify.fallbacks import get_fallback_extraction
from dualify.ollama_client import LLMClient
from dualify.phases.p01_spec_to_logic import extract_spec_logic
from dualify.phases.p02_code_to_logic import extract_code_logic
from dualify.phases.p03_smt_checking import CaseSpec, is_parseable
from dualify.runner import _normalize_extraction
from dualify.transcript import ReplayLLMClient, ResumingLLMClient
from dualify.types import BenchmarkCase, ExtractionResult

# Path-qualified IDs distinguish cases with identical names in different files.
DEV_CASE_IDS = (
    'benchmark::lifted_auto_eval::crosshair_examples_PEP316_correct_code_arith.py_double.py::double',
    'benchmark::lifted_auto_eval::crosshair_examples_PEP316_correct_code_arith.py_swap.py::swap',
    'benchmark::lifted_auto_eval::crosshair_examples_icontract_correct_code_showcase.py_zip_exact.py::zip_exact',
    'benchmark::lifted_auto_eval::python_by_contract_correct_aoc2020_day_3_toboggan_trajectory.py_parse_input.py::parse_input',
    'benchmark::lifted_auto_eval::python_by_contract_correct_aoc2020_day_22_crab_combat.py_compute_score.py::compute_score',
    'benchmark::lifted_auto_eval::crosshair_examples_icontract_correct_code_showcase.py_csv_first_column.py::csv_first_column',
)


def case_id(case: BenchmarkCase) -> str:
    """Use the original repository-discovery convention for unambiguous IDs."""
    return f"{case.file.replace('/', '::')}::{case.benchmark_id.replace('.', '::')}"


def discover_cases(root: Path) -> dict[str, BenchmarkCase]:
    cases = discover_python_cases(root / 'benchmark' / 'lifted_auto_eval', root)
    by_id = {case_id(case): case for case in cases}
    if len(cases) != 40 or len(by_id) != 40:
        raise ValueError('Expected exactly 40 distinct lifted_auto_eval cases')
    return by_id


@dataclass(frozen=True)
class ExperimentConfig:
    samples: int = 8
    model: str | None = None
    temperature: float = 0.7

    def __post_init__(self) -> None:
        if self.samples < 1:
            raise ValueError('samples must be a positive integer')
        if not 0 <= self.temperature <= 2:
            raise ValueError('temperature must be between 0 and 2')


@dataclass(frozen=True)
class ExperimentPlan:
    cases: dict[str, BenchmarkCase]
    config: ExperimentConfig

    @property
    def total_attempts(self) -> int:
        return len(self.cases) * 2 * self.config.samples


def make_plan(root: Path, config: ExperimentConfig, *, dev: bool = False,
              case_ids: list[str] | None = None) -> ExperimentPlan:
    if dev and case_ids:
        raise ValueError('--dev and --case-id cannot be combined')
    all_cases = discover_cases(root)
    selected_ids = list(DEV_CASE_IDS) if dev else case_ids
    if selected_ids is None:
        return ExperimentPlan(all_cases, config)
    if len(set(selected_ids)) != len(selected_ids):
        raise ValueError('Duplicate case IDs are not allowed')
    missing = [identifier for identifier in selected_ids if identifier not in all_cases]
    if missing:
        raise ValueError(f"Unknown case ID(s): {', '.join(missing)}")
    return ExperimentPlan(
        {identifier: all_cases[identifier] for identifier in selected_ids}, config
    )


@dataclass
class Candidate:
    case_id: str
    benchmark_id: str
    channel: Literal['spec', 'code']
    sample_index: int
    initial_response: dict[str, Any] | None
    stage_trace: dict[str, object]
    extraction_before_fallback: ExtractionResult | None
    final_extraction: ExtractionResult | None
    used_fallback: bool
    status: Literal['completed', 'error']
    errors: list[str]
    initial_call_failed: bool = False
    pipeline_failed: bool = False


class _ObservedClient:
    """Observe errors swallowed by original extraction without altering its responses."""

    def __init__(self, inner: LLMClient, initial_temperature: float) -> None:
        self.inner = inner
        self.initial_temperature = initial_temperature
        self.calls = 0
        self.initial_response: dict[str, Any] | None = None
        self.errors: list[str] = []
        self.last_call_succeeded = False
        self.successful_calls = 0
        self.initial_call_failed = False

    def healthcheck(self) -> None:
        self.inner.healthcheck()

    def generate_json(self, prompt: str, temperature: float = 0.0) -> dict:
        self.calls += 1
        self.last_call_succeeded = False
        try:
            actual_temperature = self.initial_temperature if self.calls == 1 else temperature
            response = self.inner.generate_json(prompt, temperature=actual_temperature)
        except Exception as exc:
            if self.calls == 1:
                self.initial_call_failed = True
            self.errors.append(f'{type(exc).__name__}: {exc}')
            raise
        if self.calls == 1:
            self.initial_response = response
        self.last_call_succeeded = True
        self.successful_calls += 1
        return response


def sample_plan(plan: ExperimentPlan, client: LLMClient, *,
                should_run: Callable[[str, str, int], bool] | None = None
                ) -> Iterator[Candidate]:
    """Independently invoke the original extraction once per candidate slot."""
    reject_replay(client)
    for qualified_id, case in plan.cases.items():
        case_spec = CaseSpec(benchmark_id=case.benchmark_id, arg_types=case.arg_types,
                             return_type=case.return_type)
        for channel in ('spec', 'code'):
            for index in range(plan.config.samples):
                if should_run is not None and not should_run(qualified_id, channel, index):
                    continue
                observed = _ObservedClient(client, plan.config.temperature)
                trace: dict[str, object] = {}
                before: ExtractionResult | None = None
                final: ExtractionResult | None = None
                used_fallback = False
                pipeline_failed = False
                try:
                    if channel == 'spec':
                        extraction = extract_spec_logic(
                            client=observed, benchmark_id=case.benchmark_id,
                            signature=case.signature, informal_spec=case.informal_spec,
                            return_type=case.return_type, extra_context=case.extra_context,
                            arg_types=case.arg_types)
                    else:
                        extraction = extract_code_logic(
                            client=observed, benchmark_id=case.benchmark_id,
                            signature=case.signature, function_source=case.function_source,
                            return_type=case.return_type, extra_context=case.extra_context,
                            arg_types=case.arg_types)
                    trace = dict(extraction.extraction_trace or {})
                    before = type(extraction)(**_normalize_extraction(
                        case_spec, extraction.postcondition, asdict(extraction)))
                    final = before
                    if not is_parseable(case_spec, before):
                        try:
                            final = get_fallback_extraction(case.benchmark_id)
                            used_fallback = True
                        except ValueError:
                            pass
                except Exception as exc:
                    pipeline_failed = True
                    observed.errors.append(f'{type(exc).__name__}: {exc}')
                salvaged = (before is not None and
                            before.degraded_reason == 'salvaged_partial_postcondition' and
                            observed.successful_calls > 0)
                accepted_repair = (before is not None and observed.calls > 1 and
                                   before.degraded_reason != 'sanitize_after_validation_failure')
                recovered = (not pipeline_failed and final is not None and not used_fallback and
                             ((observed.last_call_succeeded and accepted_repair) or salvaged))
                yield Candidate(
                    case_id=qualified_id, benchmark_id=case.benchmark_id,
                    channel='spec' if channel == 'spec' else 'code', sample_index=index,
                    initial_response=observed.initial_response, stage_trace=trace,
                    extraction_before_fallback=before, final_extraction=final,
                    used_fallback=used_fallback,
                    status='error' if observed.errors and not recovered else 'completed',
                    errors=observed.errors, initial_call_failed=observed.initial_call_failed,
                    pipeline_failed=pipeline_failed)


def reject_replay(client: LLMClient) -> None:
    """Cached transcript responses cannot represent independent new samples."""
    seen: set[int] = set()
    current: Any = client
    while current is not None and id(current) not in seen:
        if isinstance(current, (ReplayLLMClient, ResumingLLMClient)):
            raise ValueError('Cannot use transcript replay for independent sampling')
        seen.add(id(current))
        current = getattr(current, 'inner', None)
