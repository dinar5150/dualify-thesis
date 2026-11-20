from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "prepare_rq1_benchmark.py"


def _run_cli(
    output_dir: Path, *extra_args: str, source_root: Path = ROOT
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--source-root",
            str(source_root),
            "--output-dir",
            str(output_dir),
            "--seed",
            "20261120",
            *extra_args,
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def test_cli_creates_complete_10_30_split_and_audit(tmp_path: Path) -> None:
    result = _run_cli(tmp_path)

    assert result.returncode == 0, result.stderr
    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    audit = json.loads((tmp_path / "audit.json").read_text(encoding="utf-8"))

    ids = [case["benchmark_id"] for case in manifest["cases"]]
    assert len(ids) == len(set(ids)) == 40
    assert sum(case["split"] == "dev" for case in manifest["cases"]) == 10
    assert sum(case["split"] == "test" for case in manifest["cases"]) == 30
    assert len(audit["cases"]) == 40
    assert result.stdout.strip().endswith("SPLIT_FROZEN")


def test_cli_keeps_close_functions_with_different_names_in_one_split(tmp_path: Path) -> None:
    result = _run_cli(tmp_path)
    assert result.returncode == 0, result.stderr
    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    by_id = {case["benchmark_id"]: case for case in manifest["cases"]}

    repeated_list_ids = {
        "crosshair_examples::PEP316::correct_code::arith.py::double",
        "crosshair_examples::icontract::correct_code::arith.py::double",
        "crosshair_examples::icontract::correct_code::showcase.py::duplicate_list",
    }
    assert len({by_id[case_id]["group_id"] for case_id in repeated_list_ids}) == 1

    splits_by_group: dict[str, set[str]] = {}
    for case in manifest["cases"]:
        splits_by_group.setdefault(case["group_id"], set()).add(case["split"])
    assert all(len(splits) == 1 for splits in splits_by_group.values())


def test_verify_rejects_source_drift(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    shutil.copytree(ROOT / "benchmark", source_root / "benchmark")
    output_dir = tmp_path / "artifacts"
    generated = _run_cli(output_dir, source_root=source_root)
    assert generated.returncode == 0, generated.stderr

    input_path = next((source_root / "benchmark" / "lifted_auto_eval").glob("*.py"))
    input_path.write_bytes(input_path.read_bytes() + b"\n# drift\n")

    verified = _run_cli(output_dir, "--verify-only", source_root=source_root)
    assert verified.returncode != 0
    assert "source drift" in verified.stderr.lower()


def test_generation_is_byte_stable_and_maps_each_input_to_same_stem_gold(
    tmp_path: Path,
) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    assert _run_cli(first).returncode == 0
    assert _run_cli(second).returncode == 0
    assert (first / "manifest.json").read_bytes() == (second / "manifest.json").read_bytes()
    assert (first / "audit.json").read_bytes() == (second / "audit.json").read_bytes()

    manifest = json.loads((first / "manifest.json").read_text(encoding="utf-8"))
    for case in manifest["cases"]:
        input_path = ROOT / case["input_path"]
        gold_path = ROOT / case["gold_path"]
        assert input_path.stem == gold_path.stem
        assert case["input_sha256"] == hashlib.sha256(input_path.read_bytes()).hexdigest()
        assert case["gold_sha256"] == hashlib.sha256(gold_path.read_bytes()).hexdigest()


@pytest.mark.parametrize(
    "corruption", ["missing", "duplicate", "input_hash", "gold_hash", "split_group"]
)
def test_verify_rejects_corrupted_manifest(tmp_path: Path, corruption: str) -> None:
    output_dir = tmp_path / corruption
    assert _run_cli(output_dir).returncode == 0
    manifest_path = output_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    if corruption == "missing":
        manifest["cases"].pop()
    elif corruption == "duplicate":
        manifest["cases"][-1]["benchmark_id"] = manifest["cases"][0]["benchmark_id"]
    elif corruption == "input_hash":
        manifest["cases"][0]["input_sha256"] = "0" * 64
    elif corruption == "gold_hash":
        manifest["cases"][0]["gold_sha256"] = "0" * 64
    else:
        repeated_list = [
            case for case in manifest["cases"] if case["group_id"] == "repeated-list"
        ]
        repeated_list[0]["split"] = "test" if repeated_list[0]["split"] == "dev" else "dev"

    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    verified = _run_cli(output_dir, "--verify-only")
    assert verified.returncode != 0


def test_audit_records_case_level_leakage_and_gold_quality_evidence(tmp_path: Path) -> None:
    assert _run_cli(tmp_path).returncode == 0
    audit = json.loads((tmp_path / "audit.json").read_text(encoding="utf-8"))
    by_id = {case["benchmark_id"]: case for case in audit["cases"]}

    assert audit["summary"]["case_count"] == 40
    assert audit["summary"]["needs_attention_count"] == 7
    assert audit["summary"]["gold_readme_needs_attention_declared"] == 8
    assert audit["summary"]["gold_readme_count_discrepancy"] is True
    assert audit["summary"]["embedded_formal_annotation_case_count"] > 0
    assert audit["summary"]["weak_informal_spec_case_count"] > 0

    required_fields = {
        "benchmark_id",
        "group_id",
        "group_reason",
        "provenance",
        "embedded_formal_annotations",
        "gold_text_in_generation_input",
        "informal_spec_quality",
        "gold_quality",
    }
    assert all(required_fields <= case.keys() for case in audit["cases"])

    pep_swap = by_id["crosshair_examples::PEP316::correct_code::arith.py::swap"]
    assert pep_swap["embedded_formal_annotations"]
    assert any("post:" in item["text"] for item in pep_swap["embedded_formal_annotations"])

    duplicate = by_id[
        "crosshair_examples::icontract::correct_code::showcase.py::duplicate_list"
    ]
    assert duplicate["informal_spec_quality"]["too_general"] is True

    transform = by_id[
        "python_by_contract::correct::aoc2020::day_25_combo_breaker.py::transform"
    ]
    assert "needs_attention" in transform["gold_quality"]["limitations"]
    assert "partial_reference" in transform["gold_quality"]["limitations"]


def test_split_balances_corpus_origin_and_needs_attention_when_feasible(
    tmp_path: Path,
) -> None:
    assert _run_cli(tmp_path).returncode == 0
    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    audit = json.loads((tmp_path / "audit.json").read_text(encoding="utf-8"))
    audit_by_id = {case["benchmark_id"]: case for case in audit["cases"]}
    dev = [case for case in manifest["cases"] if case["split"] == "dev"]

    assert sum(case["benchmark_id"].startswith("crosshair_examples::") for case in dev) == 4
    assert sum(
        audit_by_id[case["benchmark_id"]]["gold_quality"]["needs_attention"]
        for case in dev
    ) == 2
    assert manifest["split_rule"]["balance_targets"] == {
        "crosshair_examples": 4,
        "needs_attention": 2,
    }


def test_cli_reports_blocked_when_no_exact_group_aware_split_exists(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    shutil.copytree(ROOT / "benchmark", source_root / "benchmark")
    benchmark_ids = []
    for path in sorted((source_root / "benchmark" / "lifted").glob("*.yaml")):
        benchmark_ids.append(yaml.safe_load(path.read_text(encoding="utf-8"))["benchmark_id"])
    group_config = {
        "schema_version": 1,
        "grouping_rules": ["synthetic impossible grouping"],
        "groups": {
            "all-cases": {
                "reason": "Synthetic negative fixture.",
                "members": benchmark_ids,
            }
        },
    }
    (source_root / "benchmark" / "rq1_groups.yaml").write_text(
        yaml.safe_dump(group_config, sort_keys=False), encoding="utf-8"
    )

    result = _run_cli(tmp_path / "artifacts", source_root=source_root)
    assert result.returncode != 0
    assert "BLOCKED: no exact group-aware 10/30 split" in result.stderr
