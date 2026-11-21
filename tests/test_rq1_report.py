"""Сквозные проверки offline-отчёта на сохранённых финальных кандидатах."""

import json
import shutil
from dataclasses import asdict
from pathlib import Path

import pytest

from dualify import gold_scoring
from dualify.phases.p03_smt_checking import CaseSpec
from dualify.rq1_attempt import AttemptRecord, LogicalCall
from dualify.rq1_report import analyze_candidate_pools, main
from dualify.types import ExtractionResult, SmtResult


def save_pool(
    root: Path, case_id: str, spec: list[str], code: list[str], *, temperature: float = 0.7,
) -> Path:
    gold_dir = root / "gold"
    gold_dir.mkdir(exist_ok=True)
    (gold_dir / f"{case_id}.yaml").write_text(
        f"benchmark_id: {case_id}\n"
        f"qualname: {case_id}\n"
        f"signature: '{case_id}(x: int)'\n"
        'return_type: int\nreference_post: "ret == x + 1"\n',
        encoding="utf-8",
    )
    pool = root / case_id
    pool.mkdir()
    (pool / "pool_config.json").write_text(
        json.dumps({
            "benchmark_id": case_id, "provider": "fake", "model": "fake-model",
            "treatment_temperature": temperature, "max_transient_retries": 0,
        }),
        encoding="utf-8",
    )
    for channel, formulas in (("spec", spec), ("code", code)):
        for index, postcondition in enumerate(formulas):
            arm = "treatment" if index else "baseline"
            slot = f"{case_id}:{channel}:{arm}:{index}"
            initial = temperature if index else 0.0
            record = AttemptRecord(
                slot_id=slot, channel=channel, model="fake-model",
                initial_temperature=initial, repair_temperature=0.0, max_transient_retries=0,
                status="completed",
                extraction=ExtractionResult(case_id, ["x"], "int", [], postcondition, "high", ""),
                calls=[LogicalCall(0, "initial", initial, 1, {})], errors=[], elapsed_seconds=0.5,
            )
            slot_dir = pool / slot.replace(":", "__")
            slot_dir.mkdir()
            (slot_dir / "result.json").write_text(json.dumps(asdict(record)), encoding="utf-8")
    return pool


def test_scores_saved_candidates_and_writes_reproducible_reports(tmp_path: Path) -> None:
    right, wrong = "ret == x + 1", "ret == x + 2"
    pool = save_pool(tmp_path, "increment", [wrong, right, wrong, wrong, wrong], [right] * 5)
    output = tmp_path / "report"
    args = [str(pool), "--gold-dir", str(tmp_path / "gold"), "--output-dir", str(output)]
    assert main(args) == 0
    files = {path.name: path.read_bytes() for path in output.iterdir()}
    tasks = json.loads(files["tasks.json"])
    summary = json.loads(files["summary.json"])
    assert tasks[0]["spec"]["low"] == {"1": 0.25, "2": 0.5, "4": 1.0}
    assert tasks[0]["spec"]["high"] == tasks[0]["spec"]["low"]
    assert tasks[0]["spec"]["candidates"][0]["reason"] == "equivalent_no_mismatch"
    assert tasks[0]["spec"]["candidates"][0]["diagnostics"]["solver_status"]
    assert tasks[0]["spec"]["unique_final_formulas"] == 2
    assert summary["spec"]["delta_4_1"] == 0.75
    assert summary["spec"]["baseline"]["equivalent"] == 0
    assert summary["spec"]["treatment"]["elapsed_seconds"] == 2.0
    assert summary["spec"]["treatment"]["logical_calls"] == 4
    assert summary["code"]["low"] == {"1": 1.0, "2": 1.0, "4": 1.0}
    assert summary["code"]["baseline"]["equivalent"] == 1
    assert main(args) == 0
    assert (output / "summary.json").read_bytes() == files["summary.json"]
    repeated = json.loads((output / "tasks.json").read_bytes())
    for channel in ("spec", "code"):
        assert repeated[0][channel]["low"] == tasks[0][channel]["low"]
        assert [r["reason"] for r in repeated[0][channel]["candidates"]] == [
            r["reason"] for r in tasks[0][channel]["candidates"]
        ]


def test_macro_average_and_paired_bootstrap_use_tasks(tmp_path: Path) -> None:
    right, wrong = "ret == x + 1", "ret == x + 2"
    pools = [
        save_pool(tmp_path, "mixed", [right, wrong, right, wrong, wrong], [wrong] * 5),
        save_pool(tmp_path, "perfect", [wrong, right, right, right, right], [wrong] * 5),
        save_pool(tmp_path, "zero", [right, wrong, wrong, wrong, wrong], [wrong] * 5),
    ]
    tasks, summary = analyze_candidate_pools(pools, gold_dir=tmp_path / "gold")
    assert summary["spec"]["low"] == {"1": 5 / 12, "2": 0.5, "4": 2 / 3}
    assert summary["spec"]["delta_4_1"] == 0.25
    assert summary["spec"]["first_k_observed"] == {"1": 1 / 3, "2": 2 / 3, "4": 2 / 3}
    assert summary["spec"]["mixed_task_fraction"] == 1 / 3
    assert summary["spec"]["bootstrap_95"]["intervals"]["delta_4_1"] == [0.0, 0.75]
    assert summary["spec"]["bootstrap_95"]["task_count"] == 3
    assert summary["code"]["bootstrap_95"]["intervals"]["delta_4_1"] == [0.0, 0.0]
    assert summary["code"]["low"] == {"1": 0.0, "2": 0.0, "4": 0.0}
    assert len(tasks) == 3
    assert analyze_candidate_pools(list(reversed(pools)), gold_dir=tmp_path / "gold")[1] == summary


def test_unknown_only_expands_high_and_invalid_keeps_original_reason(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = gold_scoring.check_equivalence

    def check(case: CaseSpec, gold: ExtractionResult, candidate: ExtractionResult) -> SmtResult:
        if candidate.postcondition == "ret == x + 3":
            return SmtResult(
                case.benchmark_id, False, "solver_unknown", None,
                {"solver_status": {"post_mismatch_check": "unknown"}}, "solver_unknown_post",
            )
        return original(case, gold, candidate)

    monkeypatch.setattr(gold_scoring, "check_equivalence", check)
    wrong = "ret == x + 2"
    pool = save_pool(
        tmp_path, "increment", [wrong, wrong, "ret == x + 3", "ret ==", wrong], [wrong] * 5,
    )
    tasks, summary = analyze_candidate_pools([pool], gold_dir=tmp_path / "gold")
    spec = tasks[0]["spec"]
    assert (spec["c"], spec["u"]) == (0, 1)
    assert spec["low"] == {"1": 0.0, "2": 0.0, "4": 0.0}
    assert spec["high"] == {"1": 0.25, "2": 0.5, "4": 1.0}
    unknown, invalid = spec["candidates"][1:3]
    assert (unknown["status"], unknown["reason"]) == ("inconclusive", "solver_unknown")
    assert unknown["diagnostics"] == {"solver_status": {"post_mismatch_check": "unknown"}}
    assert unknown["well_formedness"] == "solver_unknown_post"
    assert invalid["status"] == "invalid"
    assert invalid["reason"].startswith("formula_parse_error: ")
    assert summary["spec"]["treatment"]["invalid"] == 1
    assert summary["spec"]["treatment"]["inconclusive"] == 1


@pytest.mark.parametrize("damage", ["missing", "duplicate", "extra", "incomplete", "other_channel"])
def test_blocks_inconsistent_slots(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], damage: str,
) -> None:
    right = "ret == x + 1"
    pool = save_pool(tmp_path, "increment", [right] * 5, [right] * 5)
    slot_path = pool / "increment__spec__treatment__1" / "result.json"
    if damage == "missing":
        slot_path.unlink()
    elif damage == "duplicate":
        shutil.copytree(slot_path.parent, pool / "duplicate")
    else:
        record = json.loads(slot_path.read_text(encoding="utf-8"))
        if damage == "extra":
            record["slot_id"] = "increment:spec:treatment:5"
            slot_path = pool / "increment__spec__treatment__5" / "result.json"
            slot_path.parent.mkdir()
        elif damage == "incomplete":
            record["status"] = "incomplete"
        else:
            record["channel"] = "code"
        slot_path.write_text(json.dumps(record), encoding="utf-8")
    output = tmp_path / "report"
    assert main([str(pool), "--gold-dir", str(tmp_path / "gold"), "--output-dir", str(output)]) == 1
    assert "BLOCKED" in capsys.readouterr().err
    assert not output.exists()


def test_blocks_parse_error_in_gold_without_counting_candidate_as_invalid(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    right = "ret == x + 1"
    pool = save_pool(tmp_path, "increment", [right] * 5, [right] * 5)
    gold_dir = tmp_path / "gold"
    path = gold_dir / "increment.yaml"
    path.write_text(path.read_text(encoding="utf-8").replace(right, "ret =="), encoding="utf-8")
    output = tmp_path / "report"
    assert main([str(pool), "--gold-dir", str(gold_dir), "--output-dir", str(output)]) == 1
    error = capsys.readouterr().err
    assert "BLOCKED" in error
    assert "unclassified" in error
    assert "formula_parse_error:" in error
    assert not output.exists()


def test_unclassified_oracle_result_preserves_diagnostics(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    def check(case: CaseSpec, gold: ExtractionResult, candidate: ExtractionResult) -> SmtResult:
        return SmtResult(case.benchmark_id, False, "new_reason", None, {"stage": "test"})

    monkeypatch.setattr(gold_scoring, "check_equivalence", check)
    right = "ret == x + 1"
    pool = save_pool(tmp_path, "increment", [right] * 5, [right] * 5)
    output = tmp_path / "report"
    assert main([str(pool), "--gold-dir", str(tmp_path / "gold"), "--output-dir", str(output)]) == 1
    error = capsys.readouterr().err
    assert "BLOCKED: increment:spec:baseline:0: unclassified" in error
    assert '"reason": "new_reason"' in error
    assert '"diagnostics": {"stage": "test"}' in error
    assert not output.exists()


@pytest.mark.parametrize("change", ["temperature", "duplicate_task"])
def test_blocks_mixing_incompatible_pools(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], change: str,
) -> None:
    right = "ret == x + 1"
    pool = save_pool(tmp_path, "increment", [right] * 5, [right] * 5)
    if change == "temperature":
        second = save_pool(tmp_path, "another", [right] * 5, [right] * 5, temperature=0.4)
    else:
        second = pool
    output = tmp_path / "report"
    assert main([
        str(pool), str(second), "--gold-dir", str(tmp_path / "gold"), "--output-dir", str(output),
    ]) == 1
    assert "BLOCKED" in capsys.readouterr().err
    assert not output.exists()
