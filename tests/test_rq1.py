import json
import runpy
import socket
import subprocess
import sys
from pathlib import Path

import pytest

from dualify.rq1 import DEV_CASE_IDS, ExperimentConfig, discover_cases, make_plan

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'scripts' / 'run_rq1.py'
ORIGINAL = '7ffd1ae37822096d5b7b573785ee46e877903185'
EXPECTED_DEV = {
    'benchmark::lifted_auto_eval::crosshair_examples_PEP316_correct_code_arith.py_double.py::double',
    'benchmark::lifted_auto_eval::crosshair_examples_PEP316_correct_code_arith.py_swap.py::swap',
    'benchmark::lifted_auto_eval::crosshair_examples_icontract_correct_code_showcase.py_zip_exact.py::zip_exact',
    'benchmark::lifted_auto_eval::python_by_contract_correct_aoc2020_day_3_toboggan_trajectory.py_parse_input.py::parse_input',
    'benchmark::lifted_auto_eval::python_by_contract_correct_aoc2020_day_22_crab_combat.py_compute_score.py::compute_score',
    'benchmark::lifted_auto_eval::crosshair_examples_icontract_correct_code_showcase.py_csv_first_column.py::csv_first_column',
}


def test_full_and_dev_case_selection():
    all_cases = discover_cases(ROOT)
    assert len(all_cases) == len(set(all_cases)) == 40
    assert len(DEV_CASE_IDS) == len(set(DEV_CASE_IDS)) == 6
    assert set(DEV_CASE_IDS) == EXPECTED_DEV
    full = make_plan(ROOT, ExperimentConfig())
    dev = make_plan(ROOT, ExperimentConfig(), dev=True)
    assert set(full.cases) == set(all_cases)
    assert set(dev.cases) == EXPECTED_DEV
    swap = all_cases[next(i for i in EXPECTED_DEV if i.endswith('::swap'))]
    assert 'Tuple[int, int]' in swap.signature


@pytest.mark.parametrize(('dev', 'samples', 'expected'), [(True, 1, 12), (True, 2, 24),
                                                            (False, 8, 640)])
def test_attempt_counts(dev, samples, expected):
    assert make_plan(ROOT, ExperimentConfig(samples=samples), dev=dev).total_attempts == expected


def test_specific_selection_and_invalid_options():
    ids = list(DEV_CASE_IDS[:2])
    assert list(make_plan(ROOT, ExperimentConfig(), case_ids=ids).cases) == ids
    with pytest.raises(ValueError, match='Unknown case ID'):
        make_plan(ROOT, ExperimentConfig(), case_ids=['double'])
    with pytest.raises(ValueError, match='cannot be combined'):
        make_plan(ROOT, ExperimentConfig(), dev=True, case_ids=ids)
    with pytest.raises(ValueError, match='Duplicate'):
        make_plan(ROOT, ExperimentConfig(), case_ids=[ids[0], ids[0]])
    with pytest.raises(ValueError, match='positive'):
        ExperimentConfig(samples=0)


def test_dry_run_never_uses_network(monkeypatch, capsys):
    def forbidden(*args, **kwargs):
        raise AssertionError('Network access is forbidden')

    monkeypatch.setattr(socket, 'socket', forbidden)
    monkeypatch.setattr(sys, 'argv', [str(SCRIPT), '--dev', '--samples', '2', '--dry-run',
                                      '--model', 'example', '--temperature', '0.7'])
    with pytest.raises(SystemExit) as result:
        runpy.run_path(str(SCRIPT), run_name='__main__')
    assert result.value.code == 0
    report = json.loads(capsys.readouterr().out)
    assert report['total_planned_extraction_attempts'] == 24
    assert report['model'] == 'example' and report['initial_temperature'] == 0.7


@pytest.mark.parametrize('arguments', [
    ['--dev', '--case-id', 'bad', '--dry-run'],
    ['--case-id', 'bad', '--dry-run'],
    ['--samples', '0', '--dry-run'],
    [],
])
def test_cli_rejects_invalid_input(arguments):
    result = subprocess.run([sys.executable, str(SCRIPT), *arguments], cwd=ROOT,
                            capture_output=True, text=True, check=False)
    assert result.returncode != 0
    assert 'error:' in result.stderr


def test_original_benchmark_and_gold_unchanged():
    result = subprocess.run(['git', 'diff', '--exit-code', ORIGINAL, '--',
                             'benchmark/lifted_auto_eval', 'benchmark/lifted'],
                            cwd=ROOT, capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
