import copy
from pathlib import Path

import pytest

from dualify.gold_scoring import GoldContract
from dualify.rq1_analysis import analyze, pass_at_k
from dualify.rq1_evaluation import classify, evaluate_experiment, evaluate_record
from dualify.rq1_storage import execute
from dualify.types import BenchmarkCase

ROOT = Path(__file__).resolve().parents[1]


def case():
    return BenchmarkCase(
        "demo",
        "demo.py",
        "demo",
        1,
        "demo(x: int) -> int",
        {"x": "int"},
        "int",
        "Add one.",
        "",
        "def demo(x: int) -> int:\n    return x + 1",
    )


def gold():
    return GoldContract("demo", "demo", True, ["x"], {"x": "int"}, "int", [], "ret == x + 1")


def saved(
    *,
    post="ret == x + 1",
    status="completed",
    fallback=False,
    degraded=False,
    initial_post="ret == x + 1",
    initial_errors=None,
    repair=False,
):
    extraction = {
        "benchmark_id": "demo",
        "args": ["x"],
        "return_type": "int",
        "domain_constraints": [],
        "postcondition": post,
        "confidence": "high",
        "notes": "",
        "degraded": degraded,
        "degraded_reason": "example" if degraded else "",
        "extraction_trace": None,
    }
    trace = {
        "initial": {
            "domain_constraints": [],
            "postcondition": initial_post,
            "errors": initial_errors or [],
        }
    }
    if repair:
        trace["repair"] = {"domain_constraints": [], "postcondition": post, "errors": []}
    return {
        "case_id": "qualified",
        "benchmark_id": "demo",
        "channel": "spec",
        "sample_index": 0,
        "status": status,
        "used_fallback": fallback,
        "initial_response": {
            "args": ["x"],
            "return_type": "int",
            "domain_constraints": [],
            "postcondition": initial_post,
        },
        "stage_trace": trace,
        "final_extraction": extraction,
        "diagnostics": {"request_count": 1, "retry_count": None, "token_usage": []},
        "duration_seconds": 2.0,
    }


def test_pass_at_k_edges():
    assert pass_at_k(8, 0, 8) == 0
    assert pass_at_k(8, 1, 1) == 0.125
    assert pass_at_k(8, 1, 8) == 1
    assert pass_at_k(8, 8, 4) == 1
    with pytest.raises(ValueError):
        pass_at_k(7, 1, 8)


def test_actual_scorer_and_degraded_fallback_and_failures():
    equivalent = evaluate_record(case(), saved(degraded=True), gold())
    assert equivalent["final_outcome"] == "equivalent" and equivalent["degraded"]
    fallback = evaluate_record(case(), saved(fallback=True), gold())
    assert fallback["final_gold"]["contract_equivalent"] and fallback["final_outcome"] == "fallback"
    failed = evaluate_record(case(), saved(status="error"), gold())
    assert failed["final_gold"]["contract_equivalent"]
    assert failed["final_outcome"] == "api_or_evaluation_failure"


def test_relation_unknown_and_precise_precedence():
    score = {
        "contract_equivalent": True,
        "reason": "solver_unknown",
        "pre_relation": "equivalent",
        "post_relation": "undetermined",
    }
    assert classify(score, True) == "inconclusive"
    assert classify(score, True, fallback=True) == "fallback"
    assert classify(score, True, failed=True, fallback=True) == "api_or_evaluation_failure"
    score.update(
        reason="case_post_code", contract_equivalent=False, post_relation="generated_stronger"
    )
    assert classify(score, True) == "stronger"
    score["pre_relation"] = "generated_weaker"
    assert classify(score, True) == "unclassified"


def test_initial_final_validity_and_repair():
    row = evaluate_record(
        case(),
        saved(initial_post="ret == ret", initial_errors=["must not be tautology"], repair=True),
        gold(),
    )
    assert row["initial_validity"]["syntactic"] and row["initial_validity"]["parseable"]
    assert not row["initial_validity"]["extractor_valid"]
    assert row["final_validity"]["extractor_valid"] and row["repair_attempted"]
    assert row["initial_outcome"] == "invalid_or_unsupported"
    assert row["final_outcome"] == "equivalent"
    result = analyze(
        {
            "experiment_id": "x",
            "configuration": {},
            "selected_case_ids": ["qualified"],
            "samples": 8,
            "candidates": [row],
        }
    )
    repair = result["channels"]["spec"]["repair"]
    assert (
        repair["initially_invalid"]
        == repair["repair_attempts"]
        == repair["successful_repairs"]
        == 1
    )
    assert repair["success_per_initially_invalid"] == 1
    assert result["tasks"][0]["pass_at_k"]["8"] is None


def test_macro_and_missing_and_uniqueness():
    prototype = evaluate_record(case(), saved(), gold())
    rows = []
    ids = [f"case-{i}" for i in range(40)]
    for identifier in ids:
        for channel in ("spec", "code"):
            for index in range(8):
                row = copy.deepcopy(prototype)
                row.update(
                    case_id=identifier,
                    channel=channel,
                    sample_index=index,
                    final_outcome="equivalent" if index == 0 else "api_or_evaluation_failure",
                )
                rows.append(row)
    evaluation = {
        "experiment_id": "x",
        "configuration": {},
        "selected_case_ids": ids,
        "samples": 8,
        "candidates": rows,
    }
    result = analyze(evaluation)
    assert result["channels"]["spec"]["pass_at_k"]["final"]["1"]["macro"] == 0.125
    assert result["channels"]["spec"]["pass_at_k"]["final"]["8"]["macro"] == 1
    assert result["tasks"][0]["unique_final_contracts"] == 1
    assert result["tasks"][0]["unique_rate"] == 1 / 8
    result = analyze({**evaluation, "candidates": rows[1:]})
    assert result["channels"]["spec"]["pass_at_k"]["final"]["8"]["macro"] is None
    assert result["channels"]["spec"]["pass_at_k"]["final"]["8"]["eligible_tasks"] == 39
    assert result["tasks"][0]["pass_at_k"]["8"] is None
    with pytest.raises(ValueError, match="duplicate"):
        analyze({**evaluation, "candidates": rows + [rows[0]]})


def test_initial_missing_remains_unavailable():
    data = saved()
    data["stage_trace"] = {}
    row = evaluate_record(case(), data, gold())
    assert row["initial_outcome"] == "unavailable"
    assert row["initial_validity"] is None
    assert row["final_outcome"] == "equivalent"


def test_end_to_end_no_network_and_deterministic(tmp_path, monkeypatch):
    import socket

    from dualify.rq1 import ExperimentConfig, ExperimentPlan, discover_cases

    cases = discover_cases(ROOT)
    case_id = next(i for i in cases if i.endswith("py_determine_id.py::determine_id"))
    plan = ExperimentPlan({case_id: cases[case_id]}, ExperimentConfig(samples=1))

    class Fake:
        def healthcheck(self):
            pass

        def generate_json(self, prompt, temperature=0.0):
            return {
                "args": ["row", "column"],
                "return_type": "int",
                "domain_constraints": [],
                "postcondition": "ret == row * 8 + column",
            }

    config = {
        "benchmark": "lifted_auto_eval",
        "selected_case_ids": [case_id],
        "samples_per_channel": 1,
    }
    execute(plan, Fake(), tmp_path, config)
    monkeypatch.setattr(socket, "socket", lambda *a, **kw: pytest.fail("network accessed"))
    result = evaluate_experiment(ROOT, tmp_path)
    assert result == evaluate_experiment(ROOT, tmp_path)
    assert len(result["candidates"]) == 2
    assert analyze(result)["channels"]["spec"]["pass_at_k"]["final"]["8"]["macro"] is None


def test_n8_counts_failures_unknown_fallback_and_degraded():
    records = []
    for index in range(8):
        data = saved(
            degraded=index == 0, fallback=index == 1, status="error" if index == 2 else "completed"
        )
        data["sample_index"] = index
        row = evaluate_record(case(), data, gold())
        if index == 3:
            row["final_outcome"] = "inconclusive"
        elif index > 3:
            row["final_outcome"] = "weaker"
        records.append(row)
    result = analyze(
        {
            "experiment_id": "fake",
            "configuration": {},
            "selected_case_ids": ["qualified"],
            "samples": 8,
            "candidates": records,
        }
    )
    spec = result["tasks"][0]
    assert spec["completed"] == 8 and spec["successes"] == 1
    assert spec["pass_at_k"]["1"] == 0.125 and spec["pass_at_k"]["8"] == 1
    assert spec["outcomes"]["fallback"] == 1
    assert spec["outcomes"]["api_or_evaluation_failure"] == 1
    assert spec["outcomes"]["inconclusive"] == 1
    assert spec["degraded"] == 1


def test_no_scientific_metric_without_gold():
    data = saved(status="error")
    row = evaluate_record(case(), data, None)
    rows = [dict(row, sample_index=index) for index in range(8)]
    result = analyze(
        {
            "experiment_id": "fake",
            "configuration": {},
            "selected_case_ids": ["qualified"],
            "samples": 8,
            "candidates": rows,
        }
    )
    assert result["tasks"][0]["pass_at_k"]["1"] is None


def test_unique_key_includes_preconditions_and_normalizes_whitespace():
    first = saved()
    second = saved()
    second["final_extraction"]["domain_constraints"] = ["x > 0"]
    third = saved()
    third["final_extraction"]["postcondition"] = "ret==x+1"
    rows = [evaluate_record(case(), data, gold()) for data in (first, second, third)]
    for index, row in enumerate(rows):
        row["sample_index"] = index
    result = analyze(
        {
            "experiment_id": "test",
            "configuration": {},
            "selected_case_ids": ["qualified"],
            "samples": 8,
            "candidates": rows,
        }
    )
    assert result["tasks"][0]["unique_final_contracts"] == 2
    assert result["tasks"][0]["unique_rate"] == 2 / 3
