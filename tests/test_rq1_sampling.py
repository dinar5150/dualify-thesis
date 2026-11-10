"""RQ1 sampling tests. No live model/API calls."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import ModuleType

import pytest

from dualify.rq1_sampling import (
    FixedTemperatureClient,
    SamplingConfig,
    check_config,
    outcome_from_gold,
    pass_at_k,
    run_rq1,
    summarize_samples,
)


def test_pass_at_k_known_values() -> None:
    assert pass_at_k(8, 0, 8) == 0.0
    assert pass_at_k(8, 8, 1) == 1.0
    assert pass_at_k(8, 2, 1) == pytest.approx(2 / 8)
    assert pass_at_k(8, 2, 2) == pytest.approx(1 - (6 / 8) * (5 / 7))
    assert pass_at_k(8, 2, 8) == 1.0
    assert pass_at_k(1, 0, 1) == 0.0
    with pytest.raises(ValueError):
        pass_at_k(2, 3, 1)
    with pytest.raises(ValueError):
        pass_at_k(2, 1, 3)


def test_conservative_gold_labels() -> None:
    good = {"contract_equivalent": True, "reason": "equivalent_no_mismatch"}
    assert outcome_from_gold(good) == "equivalent"
    assert outcome_from_gold(good, weak=True) == "weak"
    assert outcome_from_gold(good, used_fallback=True) == "fallback"
    assert outcome_from_gold(
        {"contract_equivalent": False, "reason": "solver_unknown"}
    ) == "unknown"
    assert outcome_from_gold(
        {"contract_equivalent": False, "reason": "case_post_code"}
    ) == "non_equivalent"
    assert outcome_from_gold(
        {"contract_equivalent": False, "reason": "formula_parse_error"}
    ) == "invalid"


def test_holdout_guard_and_k_validation() -> None:
    assert check_config(SamplingConfig(num_samples=2, ks=(1, 2))) == (1, 2)
    with pytest.raises(ValueError, match="holdout"):
        check_config(SamplingConfig(benchmark="lifted_auto_eval_clean"))
    with pytest.raises(ValueError, match="k values"):
        check_config(SamplingConfig(num_samples=2, ks=(1, 4)))
    with pytest.raises(ValueError, match="temperature"):
        check_config(SamplingConfig(temperature=float("nan")))


def test_temperature_is_forwarded_to_all_calls() -> None:
    class FakeInner:
        def __init__(self):
            self.temperatures = []
            self.health_checks = 0

        def generate_json(self, prompt, temperature=0):
            self.temperatures.append(temperature)
            return {"postcondition": "ret == 0"}

        def healthcheck(self):
            self.health_checks += 1

    inner = FakeInner()
    wrapped = FixedTemperatureClient(inner, temperature=0.7)
    wrapped.generate_json("first")
    wrapped.generate_json("repair", temperature=0.0)
    wrapped.healthcheck()
    wrapped.healthcheck()
    assert inner.temperatures == [0.7, 0.7]
    assert inner.health_checks == 1


def test_task_ids_not_collapsed_on_duplicate_function_names() -> None:
    def one_sample(result):
        return {
            channel: {
                stage: {"outcome": result} for stage in ("initial", "final")
            } for channel in ("spec", "code")
        }

    tasks = [
        {"task_id": "PEP316::double", "samples": [one_sample("equivalent"), one_sample("unknown")]},
        {
            "task_id": "icontract::double",
            "samples": [one_sample("non_equivalent"), one_sample("non_equivalent")],
        },
    ]
    metrics = summarize_samples(tasks, (1, 2))
    assert len(metrics["per_task"]) == 2
    assert metrics["per_task"][0]["metrics"]["spec_final"]["successes"] == 1
    assert metrics["per_task"][1]["metrics"]["spec_final"]["successes"] == 0
    assert metrics["macro"]["spec_final"]["pass_at_k"]["1"] == pytest.approx(0.25)
    assert metrics["macro"]["spec_final"]["pass_at_k"]["2"] == pytest.approx(0.5)


def test_orchestration_saves_all_samples_without_llm(monkeypatch, tmp_path: Path) -> None:
    """Stub existing pipeline; verify IDs, temperature, files and pass@k."""
    root = tmp_path / "repo"
    benchmark = root / "benchmark" / "dev_small"
    benchmark.mkdir(parents=True)
    (benchmark / "manifest.json").write_text(json.dumps({"tasks": [
        {"source_stem": "PEP316_double", "id": "PEP316::double"},
        {"source_stem": "icontract_double", "id": "icontract::double"},
    ]}))
    clean = root / "benchmark" / "lifted_auto_eval_clean"
    clean.mkdir(parents=True)
    gold_dir = root / "benchmark" / "lifted"
    gold_dir.mkdir(parents=True)
    for stem in ("PEP316_double", "icontract_double"):
        for folder in (benchmark, clean):
            (folder / f"{stem}.py").write_text("def double(x: int) -> int: return x\n")
        (gold_dir / f"{stem}.yaml").write_text("reference_post: ret == x\n")

    class FakeBase:
        temps = []

        def generate_json(self, prompt, temperature=0):
            self.temps.append(temperature)
            return {"postcondition": "ret == 0"}

        def healthcheck(self):
            pass

    class FakeRecorder:
        def __init__(self, inner, transcript_path, model, base_url, provider):
            self.inner = inner
            self.transcript_path = transcript_path
            self.transcript_path.parent.mkdir(parents=True, exist_ok=True)
            self.transcript_path.write_text('{"transcript_metadata": {}}\n')

        def generate_json(self, prompt, temperature=0):
            return self.inner.generate_json(prompt, temperature=temperature)

        def healthcheck(self):
            return self.inner.healthcheck()

        def close(self):
            pass

    class FakeReplay:
        pass

    class FakeResume:
        pass

    calls = {"i": 0}

    def fake_run_experiment(*, client_override, output_dir, **kwargs):
        calls["i"] += 1
        client_override.healthcheck()
        client_override.generate_json("test-model-call")
        results = []
        for stem, gold_id in [("PEP316_double", "PEP316::double"),
                              ("icontract_double", "icontract::double")]:
            success = (calls["i"] == 1 and stem == "PEP316_double")
            score = {
                "gold_benchmark_id": gold_id,
                "contract_equivalent": success,
                "reason": "equivalent_no_mismatch" if success else "solver_unknown",
                "post_relation": "equivalent" if success else "undetermined",
                "skipped": False,
            }
            extraction = {
                "postcondition": "ret == 0", "domain_constraints": [],
                "extraction_trace": {
                    "initial": {"postcondition": "ret == 0", "domain_constraints": []}
                },
                "extractor_health": {"postcondition_is_weak": False, "final_stage": "initial"},
                "used_fallback": False,
            }
            results.append({
                "benchmark_id": "double", "file": f"benchmark/dev_small/{stem}.py",
                "arg_types": {"x": "int"}, "return_type": "int",
                "gold_scoring": {"spec": score, "code": score},
                "spec_to_logic": extraction, "code_to_logic": extraction,
            })
        (output_dir / "fake_run.json").write_text(json.dumps({"results": results}))
        return {"results": results}

    def fake_initial_score(case, channel, gold, *, cache=None):
        score = case["gold_scoring"]["spec"]
        return {"outcome": outcome_from_gold(score), "postcondition": "ret == 0", "gold": score}

    fake_runner = ModuleType("dualify.runner")
    fake_runner.ROOT = root
    fake_runner.run_experiment = fake_run_experiment
    fake_gold = ModuleType("dualify.gold_scoring")
    fake_gold.load_gold_benchmark = lambda: {}
    fake_client = ModuleType("dualify.ollama_client")
    fake_client.create_llm_client = lambda **kwargs: FakeBase()
    fake_transcript = ModuleType("dualify.transcript")
    fake_transcript.RecordingLLMClient = FakeRecorder
    fake_transcript.ReplayLLMClient = FakeReplay
    fake_transcript.ResumingLLMClient = FakeResume
    for name, module in (
        ("dualify.runner", fake_runner), ("dualify.gold_scoring", fake_gold),
        ("dualify.ollama_client", fake_client), ("dualify.transcript", fake_transcript),
    ):
        monkeypatch.setitem(sys.modules, name, module)
    monkeypatch.setattr("dualify.rq1_sampling._initial_score", fake_initial_score)

    class FakeScoreCache:
        hits = 0
        misses = 0

        def __init__(self, gold):
            pass

        def score(self, case, post, pre):
            return case["gold_scoring"]["spec"]

    monkeypatch.setattr("dualify.rq1_sampling.GoldScoreCache", FakeScoreCache)
    output = tmp_path / "out"
    result = run_rq1(SamplingConfig(num_samples=2, ks=(1, 2)), output_dir=output)
    assert result == output
    assert FakeBase.temps == [0.7, 0.7]
    assert calls["i"] == 2
    assert (output / "metrics.json").exists()
    assert (output / "samples.json").exists()
    assert (output / "candidates.csv").exists()
    assert (output / "pass_at_k.csv").exists()
    assert (output / "runs/sample_001/fake_run.json").exists()
    assert (output / "runs/sample_002/fake_run.json").exists()
    metrics = json.loads((output / "metrics.json").read_text())
    assert len(metrics["per_task"]) == 2
    assert metrics["macro"]["code_final"]["pass_at_k"]["1"] == pytest.approx(0.25)
    meta = json.loads((output / "metadata.json").read_text())
    assert meta["status"] == "completed"
    assert meta["completed_samples"] == 2
    assert len(meta["dataset_sha256"]["source_files"]) == 2
    assert len(meta["dataset_sha256"]["gold_files"]) == 2
