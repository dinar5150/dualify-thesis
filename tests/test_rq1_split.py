from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

import yaml  # type: ignore[import-untyped]

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "prepare_rq1_split.py"


def _run(output: Path, *extra: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--output",
            str(output),
            "--seed",
            "20261120",
            *extra,
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def test_cli_generates_stable_complete_manifest(tmp_path: Path) -> None:
    first = tmp_path / "first.json"
    second = tmp_path / "second.json"

    first_result = _run(first)
    second_result = _run(second)

    assert first_result.returncode == 0, first_result.stderr
    assert second_result.returncode == 0, second_result.stderr
    assert first.read_bytes() == second.read_bytes()

    manifest = json.loads(first.read_text(encoding="utf-8"))
    cases = manifest["cases"]
    ids = [case["benchmark_id"] for case in cases]
    assert len(ids) == len(set(ids)) == 40
    assert sum(case["split"] == "dev" for case in cases) == 10
    assert sum(case["split"] == "test" for case in cases) == 30

    for case in cases:
        input_path = ROOT / case["input_path"]
        gold_path = ROOT / case["gold_path"]
        assert input_path.stem == gold_path.stem
        assert case["input_sha256"] == hashlib.sha256(input_path.read_bytes()).hexdigest()
        assert case["gold_sha256"] == hashlib.sha256(gold_path.read_bytes()).hexdigest()


def test_check_rejects_corrupted_hash(tmp_path: Path) -> None:
    output = tmp_path / "manifest.json"
    assert _run(output).returncode == 0
    manifest = json.loads(output.read_text(encoding="utf-8"))
    manifest["cases"][0]["input_sha256"] = "0" * 64
    output.write_text(json.dumps(manifest), encoding="utf-8")

    result = _run(output, "--check")

    assert result.returncode != 0
    assert "does not match" in result.stderr


def _copy_benchmark(tmp_path: Path) -> tuple[Path, Path]:
    input_dir = tmp_path / "inputs"
    gold_dir = tmp_path / "gold"
    shutil.copytree(ROOT / "benchmark" / "lifted_auto_eval", input_dir)
    shutil.copytree(ROOT / "benchmark" / "lifted", gold_dir)
    return input_dir, gold_dir


def test_cli_rejects_missing_pair(tmp_path: Path) -> None:
    input_dir, gold_dir = _copy_benchmark(tmp_path)
    next(gold_dir.glob("*.yaml")).unlink()

    result = _run(
        tmp_path / "manifest.json",
        "--input-dir",
        str(input_dir),
        "--gold-dir",
        str(gold_dir),
    )

    assert result.returncode != 0
    assert "input/gold filenames differ" in result.stderr


def test_cli_rejects_duplicate_benchmark_id(tmp_path: Path) -> None:
    input_dir, gold_dir = _copy_benchmark(tmp_path)
    first, second = sorted(gold_dir.glob("*.yaml"))[:2]
    first_record = yaml.safe_load(first.read_text(encoding="utf-8"))
    second_record = yaml.safe_load(second.read_text(encoding="utf-8"))
    second_record["benchmark_id"] = first_record["benchmark_id"]
    second.write_text(yaml.safe_dump(second_record, sort_keys=False), encoding="utf-8")

    result = _run(
        tmp_path / "manifest.json",
        "--input-dir",
        str(input_dir),
        "--gold-dir",
        str(gold_dir),
    )

    assert result.returncode != 0
    assert "duplicate benchmark_id" in result.stderr
