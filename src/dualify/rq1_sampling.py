"""RQ1: repeated full-pipeline sampling and oracle pass@k evaluation.

This module uses Dualify's existing run_experiment; it does not change p01/p02
prompts, repairs, fallback behavior, action planning, or gold scoring.
"""

from __future__ import annotations

import copy
import csv
import hashlib
import json
import math
import os
import subprocess
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class SamplingConfig:
    benchmark: str = "dev_small"
    num_samples: int = 8
    temperature: float = 0.7
    ks: tuple[int, ...] = (1, 2, 4, 8)
    model: str = "qwen/qwen3.8-27b"
    base_url: str = "https://api.groq.com/openai"
    provider: str = "openai"
    allow_holdout: bool = False


class FixedTemperatureClient:
    """Apply the specified temperature to ALL LLM calls in one pipeline run.

    Initial extraction, repair and action planning all use this temperature.
    Calling the pipeline multiple times gives repeated stochastic trials, not
    independent seeds or a guarantee that responses will be distinct.
    """

    def __init__(self, inner: Any, temperature: float):
        self.inner = inner
        self.temperature = temperature
        self._healthy = False

    def generate_json(self, prompt: str, temperature: float = 0.0) -> dict:
        return self.inner.generate_json(prompt, temperature=self.temperature)

    def healthcheck(self) -> None:
        if not self._healthy:
            self.inner.healthcheck()
            self._healthy = True


def pass_at_k(n: int, c: int, k: int) -> float:
    """Standard unbiased pass@k estimate from n sampled candidates, c successes.

    P(no success in k draws without replacement) = C(n-c, k) / C(n, k).
    A sample is successful only if the chosen oracle criterion is proven.
    """
    if not 0 <= c <= n or not 1 <= k <= n:
        raise ValueError(f"Expected 0 <= c <= n and 1 <= k <= n; got n={n}, c={c}, k={k}")
    if k > n - c:
        return 1.0
    probability_no_success = 1.0
    for index in range(k):
        probability_no_success *= (n - c - index) / (n - index)
    return 1.0 - probability_no_success


def check_config(config: SamplingConfig) -> tuple[int, ...]:
    if config.num_samples < 1:
        raise ValueError("--num-samples must be positive")
    if not math.isfinite(config.temperature) or not 0 <= config.temperature <= 2:
        raise ValueError("--temperature must be finite and in [0, 2]")
    if config.benchmark not in {"dev_small", "lifted_auto_eval_clean"}:
        raise ValueError("Only dev_small and lifted_auto_eval_clean are permitted")
    if config.benchmark != "dev_small" and not config.allow_holdout:
        raise ValueError("Use --allow-holdout to run the 40-task final benchmark")
    if not config.ks:
        raise ValueError("At least one k is needed")
    if any(k < 1 or k > config.num_samples for k in config.ks):
        raise ValueError("All k values must be between 1 and --num-samples")
    if not config.model or not config.base_url:
        raise ValueError("Model and base URL must be nonempty")
    return tuple(sorted(set(config.ks)))


def outcome_from_gold(
    score: dict[str, Any], *, weak: bool = False, used_fallback: bool = False
) -> str:
    """Conservative oracle labels; never interpret solver_unknown as a proof.

    A hard-coded Dualify fallback is not LLM success. A tautological final
    postcondition is not a meaningful successful contract, even if gold is weak.
    A 'degraded' extraction can still be correct (safe_repair may succeed).
    """
    if score.get("skipped"):
        return "skipped"
    if score.get("reason") == "oracle_conflict":
        return "oracle_conflict"
    if used_fallback:
        return "fallback"
    if weak:
        return "weak"
    if score.get("contract_equivalent") is True:
        return "equivalent"
    reason = str(score.get("reason", ""))
    if reason == "solver_unknown" or (
        score.get("post_relation") == "undetermined" and reason in {"", "unknown"}
    ):
        return "unknown"
    if "parse_error" in reason or score.get("post_relation") == "parse_error":
        return "invalid"
    return "non_equivalent"


def _git_revision(root: Path) -> dict[str, Any]:
    try:
        rev = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=root, check=True, capture_output=True, text=True
        ).stdout.strip()
        dirty = bool(
            subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=root, check=True, capture_output=True, text=True,
            ).stdout.strip()
        )
        return {"commit": rev, "dirty": dirty}
    except (OSError, subprocess.CalledProcessError):
        return {"commit": None, "dirty": None}


def _manifest_path(root: Path, benchmark: str) -> Path:
    return root / "benchmark" / benchmark / "manifest.json"


def _expected_stems(root: Path, benchmark: str) -> set[str]:
    path = _manifest_path(root, benchmark)
    if not path.exists():
        raise FileNotFoundError(f"Benchmark manifest is missing: {path}")
    manifest = json.loads(path.read_text(encoding="utf-8"))
    key = "tasks" if benchmark == "dev_small" else "cases"
    return {entry["source_stem"] if benchmark == "dev_small" else entry["stem"]
            for entry in manifest[key]}


def _dataset_hashes(root: Path, benchmark: str, stems: set[str]) -> dict[str, Any]:
    """Pin the actual inputs and gold files, not only the manifest text."""
    source_dir = root / "benchmark" / benchmark
    gold_dir = root / "benchmark" / "lifted"
    hashes: dict[str, dict[str, str]] = {"source_files": {}, "gold_files": {}}
    for stem in sorted(stems):
        source_path = source_dir / f"{stem}.py"
        gold_path = gold_dir / f"{stem}.yaml"
        if not source_path.is_file() or not gold_path.is_file():
            raise FileNotFoundError(f"Missing input or gold file for {stem}")
        source_bytes = source_path.read_bytes()
        hashes["source_files"][stem] = hashlib.sha256(source_bytes).hexdigest()
        hashes["gold_files"][stem] = hashlib.sha256(gold_path.read_bytes()).hexdigest()
        # The six dev inputs must follow the same cleaning protocol as the
        # full benchmark. Do not accidentally compare dirty vs clean data.
        if benchmark == "dev_small":
            full_input_path = root / "benchmark" / "lifted_auto_eval_clean" / f"{stem}.py"
            if not full_input_path.is_file() or full_input_path.read_bytes() != source_bytes:
                raise ValueError(f"dev_small differs from the clean input: {stem}")
    return hashes


def _new_output_dir(root: Path, benchmark: str) -> Path:
    stamp = datetime.now(UTC).strftime("%Y_%m_%d_%H_%M_%S_%f")
    path = root / "results" / f"rq1_{benchmark}_{stamp}"
    path.mkdir(parents=True, exist_ok=False)
    return path


def _write_json(path: Path, content: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(content, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


class GoldScoreCache:
    """One gold evaluation per distinct contract within an RQ1 experiment.

    The existing runner scores the final extraction once. RQ1 previously scored
    its initial extraction separately, making identical formulas eligible for
    *different* Z3 verdicts. Ignore the runner's score for RQ1 metrics and
    evaluate every distinct (gold, generated) pair once using this shared cache.
    """

    def __init__(self, gold: dict[str, Any]):
        self.gold = gold
        self._scores: dict[str, dict[str, Any]] = {}
        self.hits = 0
        self.misses = 0

    def score(self, case: dict[str, Any], post: str, pre: list[str]) -> dict[str, Any]:
        from dualify.gold_scoring import lookup_gold_contract, score_extraction_against_gold
        from dualify.phases.p03_smt_checking import CaseSpec
        from dualify.types import ExtractionResult

        reference = lookup_gold_contract(
            case["benchmark_id"], self.gold, source_file=case["file"]
        )
        if reference is None:
            raise ValueError(f"No gold contract for {case['file']}")
        # Use the full gold ID. PEP316 and icontract both have a `double`.
        # Include signatures and reference formulas so changed gold cannot
        # accidentally reuse a previous evaluation within this process.
        key = json.dumps(
            {
                "gold_id": reference.benchmark_id,
                "gold_types": reference.arg_types,
                "gold_return": reference.return_type,
                "gold_pre": reference.domain_constraints,
                "gold_post": reference.postcondition,
                "generated_pre": pre,
                "generated_post": post,
            },
            sort_keys=True,
            ensure_ascii=False,
        )
        if key in self._scores:
            self.hits += 1
            return copy.deepcopy(self._scores[key])

        extraction = ExtractionResult(
            benchmark_id=case["benchmark_id"],
            args=list(case["arg_types"]),
            return_type=case["return_type"],
            domain_constraints=list(pre),
            postcondition=post,
            confidence="",
            notes="",
        )
        spec = CaseSpec(
            benchmark_id=case["benchmark_id"],
            arg_types=dict(reference.arg_types),
            return_type=reference.return_type,
        )
        result = asdict(
            score_extraction_against_gold(
                case_spec=spec, gold=reference, extraction=extraction
            )
        )
        self._scores[key] = copy.deepcopy(result)
        self.misses += 1
        return result


def _initial_score(
    case: dict[str, Any], channel: str, gold: dict[str, Any], *,
    cache: GoldScoreCache | None = None,
) -> dict[str, Any]:
    """Score initial (pre-repair) candidate using the same existing gold scorer."""
    payload = case[channel]
    initial = (payload.get("extraction_trace") or {}).get("initial") or {}
    post = initial.get("postcondition")
    pre = initial.get("domain_constraints")
    if not isinstance(post, str) or not isinstance(pre, list):
        return {"outcome": "missing", "postcondition": post, "domain_constraints": pre}

    if cache is None:
        cache = GoldScoreCache(gold)
    result = cache.score(case, post, pre)
    from dualify.runner import _is_weak_postcondition

    return {
        "postcondition": post,
        "domain_constraints": pre,
        "errors": initial.get("errors", []),
        "gold": result,
        "outcome": (
            "invalid" if initial.get("errors")
            else outcome_from_gold(result, weak=_is_weak_postcondition(post))
        ),
    }


def _final_score(
    case: dict[str, Any], channel: str, scorer_channel: str,
    *, cache: GoldScoreCache | None = None,
) -> dict[str, Any]:
    extraction = case[channel]
    original_score = case["gold_scoring"][scorer_channel]
    score = (
        cache.score(case, extraction["postcondition"], extraction["domain_constraints"])
        if cache is not None else original_score
    )
    health = extraction.get("extractor_health") or {}
    record = {
        "postcondition": extraction["postcondition"],
        "domain_constraints": extraction["domain_constraints"],
        "confidence": extraction.get("confidence"),
        "degraded": extraction.get("degraded", False),
        "degraded_reason": extraction.get("degraded_reason", ""),
        "final_stage": health.get("final_stage"),
        "used_fallback": extraction.get("used_fallback", False),
        "weak_postcondition": health.get("postcondition_is_weak", False),
        "gold": score,
        "outcome": outcome_from_gold(
            score,
            weak=bool(health.get("postcondition_is_weak", False)),
            used_fallback=bool(extraction.get("used_fallback", False)),
        ),
    }
    if cache is not None and (
        original_score.get("reason"), original_score.get("contract_equivalent")
    ) != (score.get("reason"), score.get("contract_equivalent")):
        record["original_pipeline_gold"] = original_score
    return record


def summarize_samples(task_results: list[dict[str, Any]], ks: tuple[int, ...]) -> dict[str, Any]:
    """Return per-task pass@k, macro averages and raw outcome distributions."""
    if not task_results:
        raise ValueError("No tasks to summarize")
    k_values = tuple(sorted(set(ks)))
    tasks: list[dict[str, Any]] = []
    aggregates: dict[str, dict[str, Any]] = {}
    for task in task_results:
        candidates = task["samples"]
        n = len(candidates)
        if not n or any(k > n for k in k_values):
            raise ValueError("Every task must have at least max(k) samples")
        task_metrics: dict[str, Any] = {}
        for channel in ("spec", "code"):
            for stage in ("initial", "final"):
                key = f"{channel}_{stage}"
                labels = [sample[channel][stage]["outcome"] for sample in candidates]
                c = labels.count("equivalent")
                scores = {str(k): pass_at_k(n, c, k) for k in k_values}
                counts = {label: labels.count(label) for label in sorted(set(labels))}
                task_metrics[key] = {
                    "n": n, "successes": c, "outcomes": counts, "pass_at_k": scores
                }
                aggregate = aggregates.setdefault(
                    key, {"pass_at_k": {str(k): [] for k in k_values}, "outcomes": {}}
                )
                for k in k_values:
                    aggregate["pass_at_k"][str(k)].append(scores[str(k)])
                for label, count in counts.items():
                    aggregate["outcomes"][label] = aggregate["outcomes"].get(label, 0) + count
        tasks.append({"task_id": task["task_id"], "metrics": task_metrics})
    macro = {
        key: {
            "pass_at_k": {k: sum(values) / len(values) for k, values in aggr["pass_at_k"].items()},
            "outcomes": aggr["outcomes"],
            "task_count": len(tasks),
        }
        for key, aggr in aggregates.items()
    }
    return {"k_values": list(k_values), "per_task": tasks, "macro": macro}


def _write_csv_files(output: Path, tasks: list[dict[str, Any]], metrics: dict[str, Any]) -> None:
    with (output / "candidates.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow([
            "task_id", "source_file", "sample", "channel", "stage", "outcome",
            "gold_reason", "post_relation", "degraded", "used_fallback", "postcondition",
        ])
        for task in tasks:
            for i, sample in enumerate(task["samples"], start=1):
                for channel in ("spec", "code"):
                    for stage in ("initial", "final"):
                        item = sample[channel][stage]
                        gold = item.get("gold", {})
                        writer.writerow([
                            task["task_id"], task["source_file"], i, channel, stage,
                            item["outcome"], gold.get("reason", ""),
                            gold.get("post_relation", ""), item.get("degraded", ""),
                            item.get("used_fallback", ""), item.get("postcondition", ""),
                        ])
    with (output / "pass_at_k.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(["task_id", "channel_stage", "k", "n", "successes", "pass_at_k"])
        for task in metrics["per_task"]:
            for channel_stage, data in task["metrics"].items():
                for k, value in data["pass_at_k"].items():
                    writer.writerow([
                        task["task_id"], channel_stage, k,
                        data["n"], data["successes"], value,
                    ])
        for channel_stage, data in metrics["macro"].items():
            for k, value in data["pass_at_k"].items():
                writer.writerow(["MACRO_AVERAGE", channel_stage, k, "", "", value])


def run_rq1(
    config: SamplingConfig,
    *,
    output_dir: Path | None = None,
    replay: Path | None = None,
    resume: Path | None = None,
    api_key: str = "",
    client_override: Any | None = None,
) -> Path:
    """Run n full Dualify trials per task and store all outputs.

    By default, recording is automatic. Replaying the same transcript does not
    create fresh samples; it only reproduces a previous run for inspection.
    """
    ks = check_config(config)
    if replay and resume:
        raise ValueError("--replay and --resume-transcript are mutually exclusive")
    if client_override is not None and (replay or resume):
        raise ValueError("A custom client cannot be combined with replay/resume")

    from dualify.gold_scoring import load_gold_benchmark
    from dualify.ollama_client import create_llm_client
    from dualify.runner import ROOT, run_experiment
    from dualify.transcript import RecordingLLMClient, ReplayLLMClient, ResumingLLMClient

    expected = _expected_stems(ROOT, config.benchmark)
    if not expected:
        raise ValueError("Empty benchmark manifest")
    dataset_hashes = _dataset_hashes(ROOT, config.benchmark, expected)
    output = output_dir or _new_output_dir(ROOT, config.benchmark)
    output = output.expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)
    if any(output.iterdir()):
        raise FileExistsError(f"Output directory must be empty: {output}")

    transcript_path: Path | None
    recording: Any | None = None
    base: Any | None = None
    if replay:
        transcript_path = replay.expanduser().resolve()
        recording = ReplayLLMClient.from_path(transcript_path)
    else:
        key = next(
            (value.strip() for value in (
                api_key, os.getenv("DUALIFY_API_KEY"), os.getenv("GROQ_API_KEY")
            ) if value and value.strip()),
            "",
        )
        base = client_override or create_llm_client(
            provider=config.provider, model=config.model, base_url=config.base_url, api_key=key
        )
        if resume:
            transcript_path = resume.expanduser().resolve()
            recording = ResumingLLMClient.from_path(inner=base, path=transcript_path)
        else:
            transcript_path = output / "transcript.jsonl"
            recording = RecordingLLMClient(
                inner=base, transcript_path=transcript_path,
                model=config.model, base_url=config.base_url, provider=config.provider,
            )

    # The existing ReplayLLMClient validates prompt hashes, but does not check
    # temperature, model, or provider. Validate them here so replay cannot be
    # mislabeled as a different experiment.
    if replay or resume:
        transcript_meta = getattr(recording, "metadata", {}) or {}
        for field in ("model", "base_url", "provider"):
            recorded_value = transcript_meta.get(field)
            if recorded_value and recorded_value != getattr(config, field):
                raise ValueError(
                    f"Transcript {field}={recorded_value!r} differs from "
                    f"requested {getattr(config, field)!r}"
                )
        recorded_calls = getattr(recording, "records", None)
        if recorded_calls is None:
            recorded_calls = getattr(recording, "cached_records", [])
        for call in recorded_calls:
            previous_temperature = call.get("temperature")
            if previous_temperature is None or not math.isclose(
                float(previous_temperature), config.temperature, abs_tol=1e-9
            ):
                raise ValueError("Transcript call temperature differs from --temperature")

    def retry_diagnostics() -> dict[str, Any]:
        if replay:
            return {"scope": "replay", "live_attempts": 0, "history_available": False}
        get_stats = getattr(base, "retry_diagnostics", None)
        if not callable(get_stats):
            return {"scope": "not_available"}
        return {
            "scope": "live_suffix_only" if resume else "full_live_run",
            "history_available": not bool(resume),
            **get_stats(),
        }

    client = FixedTemperatureClient(recording, config.temperature)
    manifest_bytes = _manifest_path(ROOT, config.benchmark).read_bytes()
    provenance: dict[str, Any] = {
        "started_at_utc": datetime.now(UTC).isoformat(),
        "status": "running",
        "config": {**asdict(config), "ks": list(ks)},
        "git": _git_revision(ROOT),
        "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
        "dataset_sha256": dataset_hashes,
        "transcript_path": str(transcript_path),
        "transcript_mode": "replay" if replay else "resume" if resume else "record",
        "api_retry": retry_diagnostics(),
        "success_definition": "proven gold equivalence, nonweak, no hard-coded fallback",
        "oracle_policy": (
            "one cached gold evaluation per unique (gold contract, generated contract) "
            "in this experiment"
        ),

        "unit": "full Dualify pipeline including repair, at the configured temperature",
    }
    _write_json(output / "metadata.json", provenance)

    gold = load_gold_benchmark()
    score_cache = GoldScoreCache(gold)
    tasks: dict[str, dict[str, Any]] = {}
    try:
        for sample_index in range(1, config.num_samples + 1):
            run_dir = output / "runs" / f"sample_{sample_index:03d}"
            run_dir.mkdir(parents=True, exist_ok=False)
            print(f"[RQ1] sample {sample_index}/{config.num_samples}", flush=True)
            report = run_experiment(
                model=config.model, base_url=config.base_url,
                benchmark_name=config.benchmark, provider=config.provider,
                client_override=client, output_dir=run_dir,
            )
            results = report["results"]
            seen_stems = {Path(case["file"]).stem for case in results}
            if seen_stems != expected or len(results) != len(expected):
                raise ValueError("Run contains missing or duplicate benchmark files")

            for case in results:
                stem = Path(case["file"]).stem
                gold_scoring = case.get("gold_scoring") or {}
                if not (gold_scoring.get("spec") and gold_scoring.get("code")):
                    raise ValueError(f"Missing gold result: {case['file']}")
                task_id = gold_scoring["spec"].get("gold_benchmark_id")
                if not task_id or task_id != gold_scoring["code"].get("gold_benchmark_id"):
                    raise ValueError(f"Ambiguous gold ID for {case['file']}")
                entry = tasks.setdefault(stem, {
                    "task_id": task_id, "source_file": case["file"], "samples": [],
                })
                if entry["task_id"] != task_id:
                    raise ValueError(f"Gold ID changed between samples for {stem}")
                entry["samples"].append({
                    "sample_index": sample_index,
                    "spec": {
                        "initial": _initial_score(case, "spec_to_logic", gold, cache=score_cache),
                        "final": _final_score(case, "spec_to_logic", "spec", cache=score_cache),
                    },
                    "code": {
                        "initial": _initial_score(case, "code_to_logic", gold, cache=score_cache),
                        "final": _final_score(case, "code_to_logic", "code", cache=score_cache),
                    },
                })
            provenance["completed_samples"] = sample_index
            provenance["api_retry"] = retry_diagnostics()
            provenance["oracle_cache"] = {
                "unique_contracts": score_cache.misses,
                "cache_hits": score_cache.hits,
            }
            _write_json(output / "metadata.json", provenance)

        if isinstance(recording, ReplayLLMClient) and recording.remaining_calls() != 0:
            raise ValueError(f"Transcript has {recording.remaining_calls()} unused calls")
        sorted_tasks = [tasks[stem] for stem in sorted(tasks)]
        metrics = summarize_samples(sorted_tasks, ks)
        if config.benchmark == "lifted_auto_eval_clean":
            # Explicitly separate the held-out 34 cases from the six used
            # during development. The main metrics still cover all 40.
            dev_stems = _expected_stems(ROOT, "dev_small")
            holdout_tasks = [
                task for task in sorted_tasks
                if Path(task["source_file"]).stem not in dev_stems
            ]
            if not holdout_tasks:
                raise ValueError("No holdout tasks found")
            _write_json(output / "metrics_holdout.json", summarize_samples(holdout_tasks, ks))
        _write_json(output / "samples.json", {"tasks": sorted_tasks})
        _write_json(output / "metrics.json", metrics)
        _write_csv_files(output, sorted_tasks, metrics)
        provenance["status"] = "completed"
        provenance["api_retry"] = retry_diagnostics()
        provenance["finished_at_utc"] = datetime.now(UTC).isoformat()
        _write_json(output / "metadata.json", provenance)
        return output
    except Exception as exc:
        provenance["status"] = "failed"
        provenance["api_retry"] = retry_diagnostics()
        provenance["error"] = f"{type(exc).__name__}: {exc}"
        provenance["finished_at_utc"] = datetime.now(UTC).isoformat()
        _write_json(output / "metadata.json", provenance)
        raise
    finally:
        if hasattr(recording, "close"):
            recording.close()
