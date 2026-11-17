"""Configuration and case selection for the RQ1 experiment."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from dualify.discovery import discover_python_cases
from dualify.types import BenchmarkCase

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
    temperature: float | None = None

    def __post_init__(self) -> None:
        if self.samples < 1:
            raise ValueError('samples must be a positive integer')
        if self.temperature is not None and not 0 <= self.temperature <= 2:
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
