import socket
import subprocess
from pathlib import Path

import pytest

from dualify.phases import p01_spec_to_logic, p02_code_to_logic
from dualify.rq1 import ExperimentConfig, ExperimentPlan, discover_cases, make_plan
from dualify.rq1_analysis import analyze
from dualify.rq1_diagnostics import _signature_arguments, diagnose
from dualify.rq1_evaluation import evaluate_experiment
from dualify.rq1_storage import execute, slot_key

ROOT = Path(__file__).resolve().parents[1]
BASELINE = "7ffd1ae37822096d5b7b573785ee46e877903185"


@pytest.mark.parametrize("name", ["p01_spec_to_logic.py", "p02_code_to_logic.py"])
def test_extractor_is_byte_identical_to_upstream(name):
    path = f"src/dualify/phases/{name}"
    original = subprocess.check_output(["git", "show", f"{BASELINE}:{path}"], cwd=ROOT)
    assert (ROOT / path).read_bytes() == original


def test_evaluation_rejects_extra_gold_and_modified_scorer(tmp_path):
    from dualify import rq1_evaluation

    def git(*args):
        return subprocess.check_output(["git", *args], cwd=tmp_path, text=True).strip()

    git("init", "-q")
    git("config", "user.email", "test@example.invalid")
    git("config", "user.name", "test")
    gold = tmp_path / "benchmark/lifted/a.yaml"
    scorer = tmp_path / "src/dualify/gold_scoring.py"
    for path in (gold, scorer):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("original\n")
    git("add", ".")
    git("commit", "-qm", "baseline")
    baseline = git("rev-parse", "HEAD")
    rq1_evaluation.verify_provenance(tmp_path, baseline)
    extra = gold.with_name("extra.yaml")
    extra.write_text("unexpected\n")
    with pytest.raises(ValueError, match="gold"):
        rq1_evaluation.verify_provenance(tmp_path, baseline)
    extra.unlink()
    scorer.write_text("modified\n")
    with pytest.raises(ValueError, match="scor"):
        rq1_evaluation.verify_provenance(tmp_path, baseline)


def test_markdown_shows_exploratory_dev_pass_at_k():
    import importlib.util

    spec = importlib.util.spec_from_file_location("analyze_script", ROOT / "scripts/analyze_rq1.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    rows = []
    for channel in ("spec", "code"):
        for index in range(8):
            rows.append({"case_id": "a", "channel": channel, "sample_index": index,
                         "final_outcome": "equivalent" if index == 0 else "inconclusive",
                         "initial_outcome": "unavailable", "gold_available": True})
    report = analyze({"experiment_id": "dev", "configuration": {},
                      "selected_case_ids": ["a"], "samples": 8, "candidates": rows})
    output = module._markdown(report)
    assert "Exploratory" in output
    assert "0.1250" in output
    assert "unavailable" in output


def test_full_and_dev_planning_and_original_files():
    full = make_plan(ROOT, ExperimentConfig())
    dev = make_plan(ROOT, ExperimentConfig(), dev=True)
    assert len(full.cases) == 40 and full.total_attempts == 640
    assert len(dev.cases) == 6 and set(dev.cases).issubset(full.cases)
    paths = [
        "benchmark/lifted",
        "benchmark/lifted_auto_eval",
        "src/dualify/formula_parser.py",
        "src/dualify/phases/p03_smt_checking.py",
        "src/dualify/gold_scoring.py",
        "src/dualify/relation.py",
        "src/dualify/fallbacks.py",
        "src/dualify/runner.py",
        "poetry.lock",
        "pyproject.toml",
    ]
    subprocess.run(
        ["git", "diff", "--exit-code", BASELINE, "--", *paths],
        cwd=ROOT,
        check=True,
        capture_output=True,
    )


def test_original_default_live_pipeline_fake():
    class Fake:
        def __init__(self):
            self.temperatures = []

        def generate_json(self, prompt, temperature=0.0):
            self.temperatures.append(temperature)
            return {
                "args": ["x"],
                "return_type": "int",
                "domain_constraints": [],
                "postcondition": "ret == x + 1",
            }

        def healthcheck(self):
            pass

    fake = Fake()
    p01_spec_to_logic.extract_spec_logic(
        fake, "demo", "demo(x: int) -> int", "Add one", "int", arg_types={"x": "int"}
    )
    p02_code_to_logic.extract_code_logic(
        fake,
        "demo",
        "demo(x: int) -> int",
        "def demo(x: int) -> int: return x + 1",
        "int",
        arg_types={"x": "int"},
    )
    assert fake.temperatures == [0.0, 0.0]


def test_full_offline_interruption_resume_evaluate_analyze_diagnose(tmp_path, monkeypatch):
    all_cases = discover_cases(ROOT)
    identifier = next(i for i in all_cases if i.endswith("py_determine_id.py::determine_id"))
    case = all_cases[identifier]
    plan = ExperimentPlan({identifier: case}, ExperimentConfig(samples=2, model="fake"))
    config = {
        "benchmark": "lifted_auto_eval",
        "selected_case_ids": [identifier],
        "samples_per_channel": 2,
        "git_sha": BASELINE,
        "z3_version": "4.16.0",
    }
    gold_texts = [p.read_text() for p in (ROOT / "benchmark/lifted").glob("*.yaml")]

    class Fake:
        def __init__(self, interrupt=False):
            self.calls = 0
            self.interrupt = interrupt
            self.prompts = []

        def healthcheck(self):
            pass

        def generate_json(self, prompt, temperature=0.0):
            self.calls += 1
            self.prompts.append((prompt, temperature))
            assert not any(gold in prompt for gold in gold_texts)
            assert "action plan" not in prompt.lower()
            if self.interrupt and self.calls == 1:
                raise RuntimeError("simulated provider error")
            if self.interrupt and self.calls == 3:
                raise KeyboardInterrupt()
            return {
                "args": ["row", "column"],
                "return_type": "int",
                "domain_constraints": [],
                "postcondition": "ret == row * 8 + column",
            }

    first = Fake(interrupt=True)
    with pytest.raises(KeyboardInterrupt):
        execute(plan, first, tmp_path, config)
    assert (tmp_path / "attempts" / slot_key(identifier, "spec", 0) / "result.json").exists()
    second = Fake()
    result = execute(plan, second, tmp_path, config, resume=True)
    assert result["completed"] == 4 and result["errors"] == 0
    assert len(list(tmp_path.glob("attempts/*/result.json"))) == 4
    assert execute(plan, Fake(), tmp_path, config, resume=True)["new_attempts"] == 0
    monkeypatch.setattr(socket, "socket", lambda *a, **kw: pytest.fail("network accessed"))
    evaluation = evaluate_experiment(ROOT, tmp_path)
    assert evaluation == evaluate_experiment(ROOT, tmp_path)
    assert analyze(evaluation) == analyze(evaluation)
    findings = diagnose(ROOT, tmp_path, evaluation, tmp_path / "evaluation.json")
    assert findings["counts"]["provider_failure"] >= 1
    assert findings["counts"]["repeated_identical_candidates"] == 4
    assert any(c["generation_status"] == "completed" and c["generation_errors"]
               for c in evaluation["candidates"])
    assert all(
        f["git_sha"] == BASELINE and f["generation_z3_version"] == "4.16.0"
        for f in findings["findings"]
    )
    assert all("gold" not in p.lower() for p, _ in first.prompts + second.prompts)
    assert all(t in (0.0, 0.7) for _, t in first.prompts + second.prompts)


def test_tuple_signature_parser_defect_detected():
    cases = discover_cases(ROOT)
    case = next(
        c for c in cases.values() if c.file.endswith("PEP316_correct_code_arith.py_swap.py")
    )
    assert _signature_arguments(case.signature) == ["things"]
    assert p01_spec_to_logic._extract_signature_args(case.signature) == ["things", "int]"]


def test_diagnostics_reports_signature_bug_and_unknown_without_inventing_cause(tmp_path):
    cases = discover_cases(ROOT)
    identifier = next(
        i for i, c in cases.items() if c.file.endswith("PEP316_correct_code_arith.py_swap.py")
    )
    plan = ExperimentPlan({identifier: cases[identifier]}, ExperimentConfig(samples=1))
    config = {
        "benchmark": "lifted_auto_eval",
        "selected_case_ids": [identifier],
        "samples_per_channel": 1,
        "git_sha": BASELINE,
        "z3_version": "4.16.0",
    }

    class Fake:
        def healthcheck(self):
            pass

        def generate_json(self, prompt, temperature=0.0):
            return {
                "postcondition": "ret == ret",
                "domain_constraints": [],
                "return_type": "Tuple[int, int]",
                "args": ["things"],
            }

    execute(plan, Fake(), tmp_path, config)
    evaluation = evaluate_experiment(ROOT, tmp_path)
    evaluation["candidates"][0]["final_gold"] = {
        "reason": "solver_unknown",
        "pre_relation": "undetermined",
        "post_relation": "undetermined",
    }
    report = diagnose(ROOT, tmp_path, evaluation, tmp_path / "evaluation.json")
    assert report["counts"]["signature_argument_parsing"] == 2
    assert report["counts"]["solver_unknown"] == 1
    assert "reported_timeout" not in report["counts"]
    bug = next(f for f in report["findings"] if f["category"] == "signature_argument_parsing")
    assert bug["classification"] == "confirmed_implementation_bug"
    assert bug["expected"] == ["things"] and bug["actual"] == ["things", "int]"]
    assert bug["signature"] and bug["source_record"] and bug["reproduction"]


def test_original_benchmark_runner_with_fake_client(tmp_path):
    from dualify.runner import run_experiment

    class Fake:
        def __init__(self):
            self.temperatures = []

        def healthcheck(self):
            pass

        def generate_json(self, prompt, temperature=0.0):
            self.temperatures.append(temperature)
            return {
                "args": ["x"],
                "return_type": "bool",
                "domain_constraints": [],
                "postcondition": "ret == (x > 0)",
            }

    client = Fake()
    report = run_experiment(
        model="fake",
        base_url="",
        benchmark_name="synthetic",
        client_override=client,
        output_dir=tmp_path,
        targets=["is_positive"],
    )
    assert report["summary"]["total_cases"] == 1
    assert report["results"][0]["smt_checking"]["equivalent"]
    assert all(temperature == 0.0 for temperature in client.temperatures)
    assert len(list(tmp_path.glob("synthetic_*.json"))) == 1
