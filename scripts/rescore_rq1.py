"""Re-score an existing completed RQ1 run without contacting Groq.

Only reads per-sample report JSONs and gold YAMLs. Writes to a NEW `rescored`
folder within the original result directory. Original results are unchanged.

Usage: poetry run python scripts/rescore_rq1.py results/rq1_dev_small_...
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

from dualify.gold_scoring import load_gold_benchmark
from dualify.rq1_sampling import (
    GoldScoreCache, _dataset_hashes, _expected_stems, _final_score,
    _initial_score, _write_csv_files, _write_json, summarize_samples,
)
from dualify.runner import ROOT


def rescore(folder: Path, output: Path | None = None) -> Path:
    folder = folder.expanduser().resolve()
    meta = json.loads((folder / "metadata.json").read_text(encoding="utf-8"))
    cfg = meta["config"]
    source_hashes = meta.get("dataset_sha256")
    if source_hashes is None:
        raise ValueError("This RQ1 run has no dataset hashes. Cannot verify inputs.")
    current_hashes = _dataset_hashes(ROOT, cfg["benchmark"], _expected_stems(ROOT, cfg["benchmark"]))
    if source_hashes != current_hashes:
        raise ValueError("Input or gold files differ from the recorded run; restore originals first")

    destination = (output or folder / "rescored").resolve()
    if destination.exists():
        raise FileExistsError(f"Refusing to overwrite existing output: {destination}")
    gold = load_gold_benchmark()
    cache = GoldScoreCache(gold)
    by_stem: dict[str, dict] = {}
    run_dirs = sorted((folder / "runs").glob("sample_*"))
    if len(run_dirs) != cfg["num_samples"]:
        raise ValueError(f"Expected {cfg['num_samples']} reports, found {len(run_dirs)}")
    for sample_index, run_dir in enumerate(run_dirs, start=1):
        reports = list(run_dir.glob("*.json"))
        if len(reports) != 1:
            raise ValueError(f"Expected one report in {run_dir}, found {len(reports)}")
        report = json.loads(reports[0].read_text(encoding="utf-8"))
        for case in report["results"]:
            stem = Path(case["file"]).stem
            record = by_stem.setdefault(stem, {
                "task_id": case["gold_scoring"]["spec"]["gold_benchmark_id"],
                "source_file": case["file"], "samples": [],
            })
            record["samples"].append({
                "sample_index": sample_index,
                "spec": {
                    "initial": _initial_score(case, "spec_to_logic", gold, cache=cache),
                    "final": _final_score(case, "spec_to_logic", "spec", cache=cache),
                },
                "code": {
                    "initial": _initial_score(case, "code_to_logic", gold, cache=cache),
                    "final": _final_score(case, "code_to_logic", "code", cache=cache),
                },
            })
    expected = _expected_stems(ROOT, cfg["benchmark"])
    if set(by_stem) != expected or any(len(task["samples"]) != cfg["num_samples"] for task in by_stem.values()):
        raise ValueError("Missing or duplicate tasks in saved reports")

    tasks = [by_stem[stem] for stem in sorted(by_stem)]
    metrics = summarize_samples(tasks, tuple(cfg["ks"]))
    destination.mkdir(parents=True)
    _write_json(destination / "samples.json", {"tasks": tasks})
    _write_json(destination / "metrics.json", metrics)
    if cfg["benchmark"] == "lifted_auto_eval_clean":
        dev_stems = _expected_stems(ROOT, "dev_small")
        holdout_tasks = [
            task for task in tasks if Path(task["source_file"]).stem not in dev_stems
        ]
        if len(holdout_tasks) != len(expected - dev_stems):
            raise ValueError("Holdout task count differs from frozen split")
        _write_json(
            destination / "metrics_holdout.json",
            summarize_samples(holdout_tasks, tuple(cfg["ks"])),
        )
    _write_csv_files(destination, tasks, metrics)
    _write_json(destination / "rescore_metadata.json", {
        "source_results": str(folder),
        "rescored_at_utc": datetime.now(UTC).isoformat(),
        "original_git": meta.get("git"),
        "original_model": cfg.get("model"),
        "original_temperature": cfg.get("temperature"),
        "z3_evaluation": "unique gold + candidate scored once per run",
        "cache_unique_contracts": cache.misses,
        "cache_hits": cache.hits,
    })
    print("[rescore] Unique gold evaluations:", cache.misses)
    print("[rescore] Cache hits:", cache.hits)
    print("[rescore] Macro pass@k:")
    for name in ("spec_final", "code_final"):
        print(" ", name, metrics["macro"][name]["pass_at_k"])
    print("[rescore] Results:", destination)
    return destination


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_directory", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    rescore(args.run_directory, args.output)


if __name__ == "__main__":
    main()
