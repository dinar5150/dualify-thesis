"""Keep the development slice reproducible and paired with the right gold."""

import json
from pathlib import Path

import yaml

from dualify.discovery import discover_python_cases
from dualify.gold_scoring import load_gold_benchmark, lookup_gold_contract
from dualify.runner import run_experiment
from dualify.transcript import RecordingLLMClient, ReplayLLMClient

ROOT = Path(__file__).resolve().parents[1]
BENCHMARK = ROOT / "benchmark"
DEV = BENCHMARK / "dev_small"


def test_dev_small_manifest_sources_and_gold() -> None:
    manifest = json.loads((DEV / "manifest.json").read_text())
    entries = manifest["tasks"]
    assert len(entries) == len({entry["id"] for entry in entries}) == 6
    stems = [entry["source_stem"] for entry in entries]
    assert len(stems) == len(set(stems))
    assert sorted(p.stem for p in DEV.glob("*.py")) == sorted(stems)
    gold = load_gold_benchmark()
    cases = discover_python_cases(DEV, ROOT)
    assert len(cases) == 6
    for case in cases:
        stem = Path(case.file).stem
        entry = next(item for item in entries if item["source_stem"] == stem)
        record = yaml.safe_load((BENCHMARK / "lifted" / f"{stem}.yaml").read_text())
        assert record["status"] == "confirmed"
        assert record["benchmark_id"] == entry["id"]
        assert (
            lookup_gold_contract(case.benchmark_id, gold, source_file=case.file).benchmark_id
            == entry["id"]
        )
        clean_source = (BENCHMARK / "lifted_auto_eval_clean" / f"{stem}.py").read_text()
        assert (DEV / f"{stem}.py").read_text() == clean_source


class OfflineClient:
    def healthcheck(self) -> None:
        pass

    def generate_json(self, prompt: str, temperature: float = 0.0) -> dict:
        return {"postcondition": "ret == ret", "domain_constraints": []}


def test_dev_small_offline_record_replay_and_gold(tmp_path: Path) -> None:
    transcript = tmp_path / "baseline.jsonl"
    recorder = RecordingLLMClient(OfflineClient(), transcript, "offline", "offline", "openai")
    report = run_experiment(
        "offline", "offline", "dev_small", client_override=recorder, output_dir=tmp_path
    )
    recorder.close()
    replay = ReplayLLMClient.from_path(transcript)
    replayed = run_experiment(
        "offline", "offline", "dev_small", client_override=replay, output_dir=tmp_path
    )
    assert report["summary"]["total_cases"] == 6
    assert report["summary"]["gold_scoring"]["scorable_cases"] == 6
    assert all("gold_scoring" in case for case in report["results"])
    assert [c["gold_scoring"]["gold_benchmark_id"] for c in report["results"]] == [
        c["gold_scoring"]["gold_benchmark_id"] for c in replayed["results"]
    ]
    assert replay.remaining_calls() == 0
    assert list(tmp_path.glob("dev_small_*.json"))
