import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path.cwd()
SCRIPT = ROOT / "scripts" / "prepare_rq1_split.py"


# Тестируем именно команду, которую будет запускать исследователь,
# а не только внутреннюю функцию создания manifest.
def _run(output: Path, *extra: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--output",
            str(output),
            *extra,
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


# Один и тот же seed обязан давать тот же файл и ровно 10 dev / 30 test.
def test_cli_generates_stable_complete_manifest(tmp_path: Path) -> None:
    first = tmp_path / "first.json"
    second = tmp_path / "second.json"

    first_result = _run(first)
    second_result = _run(second)

    assert first_result.returncode == 0, first_result.stderr
    assert second_result.returncode == 0, second_result.stderr
    assert first.read_bytes() == second.read_bytes()
    assert first.read_bytes() == (ROOT / "docs/rq1/benchmark-manifest.json").read_bytes()

    manifest = json.loads(first.read_text(encoding="utf-8"))
    assert "source_commit" not in manifest
    cases = manifest["cases"]
    ids = [case["benchmark_id"] for case in cases]
    assert len(ids) == len(set(ids)) == 40
    assert sum(case["split"] == "dev" for case in cases) == 10
    assert sum(case["split"] == "test" for case in cases) == 30

    # У каждой задачи есть соответствующий gold; хеши должны совпадать с файлами.
    for case in cases:
        input_path = ROOT / case["input_path"]
        gold_path = ROOT / case["gold_path"]
        assert input_path.stem == gold_path.stem
        assert case["input_sha256"] == hashlib.sha256(input_path.read_bytes()).hexdigest()
        assert case["gold_sha256"] == hashlib.sha256(gold_path.read_bytes()).hexdigest()


# Подменяем сохранённый хеш: --check должен заметить изменение,
# даже если все имена и количество примеров остались прежними.
def test_check_rejects_corrupted_hash(tmp_path: Path) -> None:
    output = tmp_path / "manifest.json"
    assert _run(output).returncode == 0
    manifest = json.loads(output.read_text(encoding="utf-8"))
    manifest["cases"][0]["input_sha256"] = "0" * 64
    output.write_text(json.dumps(manifest), encoding="utf-8")

    result = _run(output, "--check")

    assert result.returncode != 0
    assert "does not match" in result.stderr


# Seed зафиксирован протоколом, поэтому CLI не должен позволять его менять.
def test_cli_rejects_custom_seed(tmp_path: Path) -> None:
    result = _run(tmp_path / "manifest.json", "--seed", "1")

    assert result.returncode != 0
    assert "unrecognized arguments: --seed 1" in result.stderr
