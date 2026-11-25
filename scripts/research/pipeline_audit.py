"""Offline diagnostics and extractor-only validation ablation."""

import argparse
import hashlib
import json
import re
import shutil
import tarfile
from collections import Counter, defaultdict
from collections.abc import Iterator
from concurrent.futures import ProcessPoolExecutor
from contextlib import ExitStack, contextmanager
from copy import deepcopy
from dataclasses import replace
from math import comb
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Literal
from unittest.mock import patch

import requests
import z3

from dualify.discovery import discover_python_cases
from dualify.gold_scoring import GoldContract, load_gold_benchmark
from dualify.ollama_client import _extract_json_object
from dualify.phases import p01_spec_to_logic, p02_code_to_logic, p03_smt_checking
from dualify.rq1_attempt import run_extraction_attempt
from dualify.types import BenchmarkCase, ExtractionResult

Variant = Literal["baseline", "benchmark_id", "literals", "both", "both_with_nonzero_domain"]
EXTRACTORS = (p01_spec_to_logic, p02_code_to_logic)
VARIANTS: tuple[Variant, ...] = (
    "baseline", "benchmark_id", "literals", "both", "both_with_nonzero_domain",
)
ARCHIVE = Path("docs/rq1/artifacts/dev-2026-11-22-vpn.tar.gz")
STAGES = ("initial", "repair", "safe_repair")
Exchange = tuple[str, dict | None]


def _typecheck_without_call_rewrite(
    arg_types: dict[str, str],
    return_type: str,
    domain_constraints: list[str],
    postcondition: str,
) -> bool:
    # A nonempty identifier absent from the formula disables the spurious match for "(".
    benchmark_id = "__rq1_typecheck_only__"
    case = p03_smt_checking.CaseSpec(benchmark_id, arg_types, return_type)
    candidate = ExtractionResult(
        benchmark_id, list(arg_types), return_type, domain_constraints, postcondition, "", "",
    )
    return p03_smt_checking.is_parseable(case, candidate)


def _typecheck_with_implied_nonzero_domain(
    arg_types: dict[str, str],
    return_type: str,
    domain_constraints: list[str],
    postcondition: str,
) -> bool:
    # A top-level strict comparison with zero entails nonzero on the whole domain.
    # Supply this redundant fact to the existing literal guard during validation only.
    redundant_guards = []
    for name, type_name in arg_types.items():
        if type_name != "int":
            continue
        identifier = re.escape(name)
        strict_sign_test = rf"(?:{identifier}\s*[<>]\s*0|0\s*[<>]\s*{identifier})"
        if any(re.fullmatch(strict_sign_test, constraint) for constraint in domain_constraints):
            redundant_guards.append(f"{name} != 0")
    return _typecheck_without_call_rewrite(
        arg_types, return_type, domain_constraints + redundant_guards, postcondition,
    )


@contextmanager
def validation_variant(variant: Variant) -> Iterator[None]:
    """Apply one research condition during serial p01/p02 calls in this process."""
    if variant not in VARIANTS:
        raise ValueError(f"Unknown validation variant: {variant}")
    with ExitStack() as stack:
        for extractor in EXTRACTORS:
            if variant in ("benchmark_id", "both"):
                stack.enter_context(patch.object(
                    extractor, "extraction_parseable", _typecheck_without_call_rewrite,
                ))
            if variant == "both_with_nonzero_domain":
                stack.enter_context(patch.object(
                    extractor, "extraction_parseable", _typecheck_with_implied_nonzero_domain,
                ))
            if variant in ("literals", "both", "both_with_nonzero_domain"):
                stack.enter_context(patch.object(
                    extractor, "_ALLOWED_CALLS", extractor._ALLOWED_CALLS | {"Char", "String"},
                ))
        yield


class ArchiveReplay:
    """Return a saved reply only to the identical historical prompt."""

    def __init__(self, exchanges: list[Exchange]) -> None:
        self.exchanges = exchanges
        self.matched_calls = 0
        self.censored: str | None = None

    def generate_json(self, prompt: str, temperature: float = 0.0) -> dict:
        index = self.matched_calls
        if index >= len(self.exchanges):
            self.censored = "new_call"
        elif self.exchanges[index][0] != prompt:
            self.censored = "changed_prompt"
        if self.censored is not None:
            raise RuntimeError("No recorded response to this prompt")
        self.matched_calls += 1
        response = self.exchanges[index][1]
        if response is None:
            # The historical error was model-output formatting, eligible for native repair.
            error_response = requests.Response()
            error_response.status_code = 400
            error_response._content = b'{"error":"failed_generation"}'
            raise requests.HTTPError(response=error_response)
        return deepcopy(response)

    def healthcheck(self) -> None:
        return None


def _load_cases(root: Path, manifest: dict) -> dict[str, BenchmarkCase]:
    # Discovery only sees the ten explicitly named, hash-verified DEV source files.
    with TemporaryDirectory() as scratch:
        directory = Path(scratch)
        for row in manifest["dev_cases"]:
            if row["split"] != "dev":
                raise ValueError("Archive manifest names a non-dev input")
            path = Path(row["input_path"])
            if hashlib.sha256((root / path).read_bytes()).hexdigest() != row["input_sha256"]:
                raise ValueError(f"Dev input differs from archive manifest: {path}")
            (directory / path).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(root / path, directory / path)
        discovered = discover_python_cases(directory / "benchmark/lifted_auto_eval", directory)
    cases = {}
    for row in manifest["dev_cases"]:
        benchmark_id = row["benchmark_id"]
        case, = [
            case for case in discovered
            if case.file == row["input_path"]
            and benchmark_id.endswith("::" + case.qualname.replace(".", "::"))
        ]
        cases[benchmark_id] = replace(case, benchmark_id=benchmark_id)
    return cases


def _read_archive(root: Path) -> tuple[dict, dict, dict, dict]:
    with tarfile.open(root / ARCHIVE) as archive:
        names = sorted(archive.getnames())
        archive_root = names[0].rstrip("/")

        def read(name: str) -> dict:
            member = archive.extractfile(name)
            if member is None:
                raise ValueError(f"Missing archive member {name}")
            return json.load(member)

        manifest = read(f"{archive_root}/preflight.json")
        records = {}
        http = defaultdict(list)
        for name in names:
            if name.endswith("/result.json"):
                record = read(name)
                records[record["slot_id"]] = record
            elif "/http/" in name and name.endswith(".json"):
                response = read(name)
                http[response["slot_id"]].append((Path(name).name, response))
        diagnostics = read(f"{archive_root}/offline-diagnostics.json")
    if set(manifest["planned_slots"]) != records.keys() or records.keys() != http.keys():
        raise ValueError("Archive does not contain exactly the planned slots")
    return manifest, records, http, diagnostics


def _load_dev_gold(root: Path, manifest: dict, benchmark_ids: set[str]) -> dict[str, GoldContract]:
    with TemporaryDirectory() as scratch:
        for row in manifest["dev_cases"]:
            if row["benchmark_id"] not in benchmark_ids:
                continue
            if row["split"] != "dev":
                raise ValueError("Archive manifest names non-dev gold")
            gold_path = root / row["gold_path"]
            if hashlib.sha256(gold_path.read_bytes()).hexdigest() != row["gold_sha256"]:
                raise ValueError(f"Dev gold differs from archive manifest: {gold_path}")
            shutil.copyfile(gold_path, Path(scratch) / gold_path.name)
        return load_gold_benchmark(Path(scratch), require_unique_ids=True)


def _transport(
    manifest: dict, records: dict, http: dict,
) -> tuple[dict[str, Any], dict[str, list[Exchange]]]:
    statuses: Counter[str] = Counter()
    fingerprints: Counter[str] = Counter()
    identifier_set = set()
    models: Counter[str] = Counter()
    finish_reasons: Counter[str] = Counter()
    retries_by_stage: Counter[str] = Counter()
    file_ids_with_model_format_error = []
    cache_fields_observed = 0
    treatment_initial_text: Counter[str] = Counter()
    cached_prompt_token_observations = 0
    exchanges: dict[str, list[Exchange]] = {}
    for slot, record in records.items():
        latest_attempt = http[slot][-1][1].get("attempt")
        terminals: list[Exchange] = []
        for filename, row in http[slot]:
            status = row["status"]
            statuses[str(status)] += 1
            if row.get("attempt") != latest_attempt:
                assert status == 429
                retries_by_stage["superseded_attempt"] += 1
                continue
            if status == 429:
                retries_by_stage[STAGES[len(terminals)]] += 1
                continue
            payload = row["payload"]
            call = record["calls"][len(terminals)]
            assert payload["model"] == manifest["model"]
            assert payload["temperature"] == call["temperature"]
            assert payload["reasoning_effort"] == manifest["reasoning_effort"]
            assert payload["max_tokens"] == manifest["max_output_tokens"]
            assert payload["response_format"] == {"type": manifest["response_format"]}
            assert payload["messages"][0] == {
                "role": "system", "content": "Return only a strict JSON object.",
            }
            body = json.loads(row["body"])
            if status == 200:
                identifier = body["id"]
                assert identifier not in identifier_set
                identifier_set.add(identifier)
                fingerprints[body.get("system_fingerprint", "(absent)")] += 1
                models[body["model"]] += 1
                choice, = body["choices"]
                finish_reasons[choice["finish_reason"]] += 1
                usage = body["usage"]
                cache_fields_observed += any("cache" in key.lower() for key in usage)
                cached_prompt_token_observations += "prompt_tokens_details" in usage
                content = choice["message"]["content"]
                if not terminals and ":treatment:" in slot:
                    treatment_initial_text[content] += 1
                reply = _extract_json_object(content)
            else:
                assert status == 400 and body["error"]["code"] == "json_validate_failed"
                file_ids_with_model_format_error.append(filename)
                reply = None
            assert reply == call["response"]
            terminals.append((payload["messages"][1]["content"], reply))
        assert len(terminals) == len(record["calls"])
        exchanges[slot] = terminals
    report = {
        "physical_posts": statuses.total(),
        "http_statuses": dict(statuses),
        "logical_calls": sum(map(len, exchanges.values())),
        "repair_calls": sum(len(steps) - 1 for steps in exchanges.values()),
        "physical_non_completion_retries": dict(retries_by_stage),
        "unique_completion_ids": len(identifier_set),
        "model": dict(models),
        "system_fingerprint_counts": dict(fingerprints),
        "finish_reasons": dict(finish_reasons),
        "cache_field_observations": cache_fields_observed,
        "usage_prompt_token_detail_observations": cached_prompt_token_observations,
        "model_format_error_http_files": sorted(file_ids_with_model_format_error),
        "treatment_initial_text_repetition": {
            "successful_replies": treatment_initial_text.total(),
            "distinct_texts": len(treatment_initial_text),
            "duplicate_text_groups": sum(count > 1 for count in treatment_initial_text.values()),
        },
    }
    return report, exchanges


def _compare_replays(manifest: dict, records: dict, cases: dict, exchanges: dict) -> dict:
    variants = {}
    for variant in VARIANTS:
        known: Counter[str] = Counter()
        censored: Counter[str] = Counter()
        censored_slots = {}
        finals: Counter[str] = Counter()
        edited_finals = {}
        saved_calls = 0
        with validation_variant(variant):
            for slot, historical in records.items():
                archived = historical["extraction"]
                case = cases[archived["benchmark_id"]]
                client = ArchiveReplay(exchanges[slot])
                replay = run_extraction_attempt(
                    client, slot_id=slot, case=case, channel=historical["channel"],
                    model=historical["model"],
                    initial_temperature=historical["initial_temperature"],
                )
                if client.censored:
                    reason = f"{STAGES[client.matched_calls]}:{client.censored}"
                    censored[reason] += 1
                    censored_slots[slot] = reason
                    continue
                extraction = replay.extraction
                assert extraction.extraction_trace is not None
                final = extraction.extraction_trace["final"]
                earlier = replay.logical_call_count < len(historical["calls"])
                known["earlier_return" if earlier else "complete_exact_prompt_replay"] += 1
                saved_calls += len(historical["calls"]) - replay.logical_call_count
                finals[extraction.degraded_reason or STAGES[replay.logical_call_count - 1]] += 1
                assert replay.status == "completed"
                assert replay.logical_call_count == client.matched_calls
                if variant == "baseline":
                    assert extraction.extraction_trace == archived["extraction_trace"]
                if earlier or final != archived["extraction_trace"]["final"]:
                    edited_finals[slot] = {
                        "calls": replay.logical_call_count,
                        "historical_calls": len(historical["calls"]),
                        "domain": extraction.domain_constraints,
                        "postcondition": extraction.postcondition,
                        "prior_domain": archived["domain_constraints"],
                        "prior_postcondition": archived["postcondition"],
                    }
        variants[variant] = {
            "identified_outcomes": dict(known),
            "censored": dict(censored),
            "censored_slots": censored_slots,
            "identified_final_stages": dict(finals),
            "identified_fewer_calls": saved_calls,
            "changed_identified_outcomes": edited_finals,
        }
    assert variants["baseline"]["identified_outcomes"] == {
        "complete_exact_prompt_replay": len(manifest["planned_slots"]),
    }
    return variants


def _repair_diagnostics(cases: dict, records: dict, exchanges: dict) -> dict:
    safe_prompts: dict[str, set[str]] = defaultdict(set)
    domain_dropped: Counter[str] = Counter()
    for slot, steps in exchanges.items():
        record = records[slot]
        initial = steps[0][1] or {}
        domain = initial.get("domain_constraints")
        extraction = record["extraction"]
        if isinstance(domain, list) and domain and not extraction["domain_constraints"]:
            domain_dropped["all"] += 1
            case = cases[extraction["benchmark_id"]]
            if _typecheck_without_call_rewrite(case.arg_types, case.return_type, domain, "True"):
                domain_dropped["initial_domain_parseable"] += 1
        if len(steps) == 3:
            safe_prompts[steps[2][0]].add(json.dumps(steps[0][1], sort_keys=True))
    return {
        "domain_drops_after_nonempty_initial_domain": dict(domain_dropped),
        "distinct_safe_subset_prompts": len(safe_prompts),
        "safe_subset_prompt_groups_with_different_initial_responses": sum(
            len(initials) > 1 for initials in safe_prompts.values()
        ),
        "repair_context": (
            "Ordinary repair receives signature, errors, and normalized payload. "
            "It has no original code/spec section. Safe-subset repair receives original "
            "code/spec and extra context, and omits the earlier candidates and errors."
        ),
    }


def _semantic_witnesses(root: Path, manifest: dict, variants: dict) -> dict:
    changes = variants["both"]["changed_identified_outcomes"]
    zipped_slot = next(slot for slot in changes if slot.endswith("zipped_pairs:spec:treatment:4"))
    zipped_id = zipped_slot.rsplit(":", 3)[0]
    zipped = changes[zipped_slot]
    gold = _load_dev_gold(root, manifest, {zipped_id})[zipped_id]
    case = p03_smt_checking.CaseSpec(gold.benchmark_id, gold.arg_types, gold.return_type)
    results = {}
    for label, domain, post in (
        ("prior", zipped["prior_domain"], zipped["prior_postcondition"]),
        ("corrected", zipped["domain"], zipped["postcondition"]),
    ):
        gold_result = ExtractionResult(
            gold.benchmark_id, gold.args, gold.return_type,
            gold.domain_constraints, gold.postcondition, "", "",
        )
        candidate = ExtractionResult(
            gold.benchmark_id, gold.args, gold.return_type, domain, post, "", "",
        )
        results[label] = p03_smt_checking.check_equivalence(case, gold_result, candidate).reason
    assert results == {"prior": "case_post_spec", "corrected": "equivalent_no_mismatch"}
    # The two Python slices always have the same length, so strict zip reproduces length.
    n, length = z3.Ints("n length")
    solver = z3.Solver()
    solver.add(n >= 0, length == z3.If(n >= 2, n - 1, 0))
    solver.add(length != z3.If(n > 0, n - 1, 0))
    assert solver.check() == z3.unsat
    lengths = [len(list(zip(xs[:-1], xs[1:], strict=True))) for xs in map(range, range(6))]
    assert lengths == [0, 0, 1, 2, 3, 4]

    next_slot = next(slot for slot in changes if slot.endswith("next_departure:code:treatment:3"))
    departure = changes[next_slot]
    assert departure["prior_postcondition"] == (
        "And(ret >= min_time, ret % bus_id == 0, ret - min_time < bus_id)"
    )
    assert departure["postcondition"] == "And(ret >= min_time, ret - min_time < bus_id)"
    bus_id, min_time, wrong_ret = 2, 3, 3
    assert wrong_ret >= min_time and wrong_ret - min_time < bus_id and wrong_ret % bus_id != 0
    assert min_time + (-min_time % bus_id) == 4
    prior = ExtractionResult(
        "", ["bus_id", "min_time"], "int", departure["prior_domain"],
        departure["prior_postcondition"], "", "",
    )
    guard_rejection = p03_smt_checking._validate_formula_safety(prior)
    assert guard_rejection == ["unguarded_mod_denominator:bus_id"]
    with_guards = variants["both_with_nonzero_domain"]["changed_identified_outcomes"][next_slot]
    assert with_guards["domain"] == ["bus_id > 0"]
    assert with_guards["calls"] == 1
    bus, t, ret = z3.Ints("bus_id min_time ret")
    corrected_post = p03_smt_checking._safe_eval(
        with_guards["postcondition"], {"bus_id": bus, "min_time": t, "ret": ret},
        "__rq1_typecheck_only__",
    )
    solver = z3.Solver()
    solver.set(timeout=5000)
    remainder = t % bus
    original_python_branch = z3.If(remainder == 0, t, t - remainder + bus)
    solver.add(bus > 0, z3.Xor(corrected_post, ret == original_python_branch))
    assert solver.check() == z3.unsat
    return {
        "zipped_pairs": {
            "slot": zipped_slot,
            "unchanged_oracle_reasons": results,
            "python_lengths_at_input_lengths_0_through_5": lengths,
            "direct_smt_mismatch_with_slice_zip_length": "unsat",
        },
        "next_departure": {
            "slot": next_slot,
            "guard_rejection": guard_rejection,
            "code_output_on_bus_2_min_time_3": 4,
            "wrong_result_accepted_after_salvage": wrong_ret,
            "nonzero_domain_ablation_smt_code_post_mismatch": "unsat",
            "nonzero_domain_ablation_still_omits_gold_constraint": "min_time >= 0",
        },
    }


def _strict_check(item: tuple[GoldContract, tuple[str, ...], str]) -> tuple[str, str]:
    gold, domain, post = item
    case = p03_smt_checking.CaseSpec(gold.benchmark_id, gold.arg_types, gold.return_type)
    reference = ExtractionResult(
        gold.benchmark_id, gold.args, gold.return_type,
        gold.domain_constraints, gold.postcondition, "", "",
    )
    candidate = replace(reference, domain_constraints=list(domain), postcondition=post)
    try:
        smt = p03_smt_checking.check_equivalence(case, reference, candidate)
    except z3.Z3Exception:
        return "unclassified", "solver_exception"
    if smt.equivalent:
        return "equivalent", smt.reason
    if smt.reason in ("solver_unknown", "vacuous_equivalence"):
        return "inconclusive", smt.reason
    if smt.counterexample is not None and smt.reason in (
        "case_pre_code", "case_pre_spec", "case_post_code", "case_post_spec",
    ):
        return "non_equivalent", smt.reason
    if smt.reason.startswith("formula_parse_error:") and (
        p03_smt_checking.is_parseable(case, reference)
        and not p03_smt_checking.is_parseable(case, candidate)
    ):
        return "invalid", smt.reason
    return "unclassified", smt.reason


def _strict_ablation(
    root: Path, manifest: dict, archived: dict, variants: dict, workers: int,
) -> dict:
    dev_ids = {row["benchmark_id"] for row in manifest["dev_cases"]}
    comparable_ids = dev_ids.difference(archived["unclassified_tasks"])
    outcomes = {
        row["slot_id"]: (row["status"], row["reason"]) for row in archived["scores"]
        if row["slot_id"].rsplit(":", 3)[0] in comparable_ids
    }
    gold = _load_dev_gold(root, manifest, comparable_ids)
    changed = {}
    for variant, stats in variants.items():
        for slot, row in stats["changed_identified_outcomes"].items():
            benchmark_id = slot.rsplit(":", 3)[0]
            if benchmark_id in comparable_ids:
                changed[variant, slot] = (benchmark_id, tuple(row["domain"]), row["postcondition"])
    unique = sorted(set(changed.values()))
    with ProcessPoolExecutor(max_workers=workers) as pool:
        tasks = [(gold[bid], domain, post) for bid, domain, post in unique]
        scores = pool.map(_strict_check, tasks)
        result = dict(zip(unique, scores, strict=True))
    summaries = {}
    for variant, stats in variants.items():
        scored = dict(outcomes)
        for (arm, slot), formula in changed.items():
            if arm == variant:
                scored[slot] = result[formula]
        for slot, reason in stats["censored_slots"].items():
            if slot in scored:
                scored[slot] = ("censored", reason)
        summaries[variant] = _strict_summary(scored)
    return {
        "nine_task_cohort": sorted(comparable_ids),
        "method": (
            "Original p03 and RQ1 status criteria. Unchanged final formulas retain archived "
            "verdicts. Changed identified finals are rescored. The same nine DEV tasks "
            "with parseable gold are used in every variant. Bounds treat inconclusive, "
            "unclassified and censored outcomes as failure/success, respectively."
        ),
        "variants": summaries,
    }


def _strict_summary(outcomes: dict[str, tuple[str, str]]) -> dict:
    pools: dict[tuple[str, str], Counter[str]] = defaultdict(Counter)
    for slot, (status, _) in outcomes.items():
        benchmark_id, channel, condition, _ = slot.rsplit(":", 3)
        if condition == "treatment":
            pools[benchmark_id, channel][status] += 1
    report = {}
    for channel in ("spec", "code"):
        counts = [items for (_, arm), items in pools.items() if arm == channel]
        lower = [count["equivalent"] for count in counts]
        upper = [
            lower[index] + count["inconclusive"] + count["unclassified"] + count["censored"]
            for index, count in enumerate(counts)
        ]
        report[channel] = {
            str(k): [
                sum(1 - comb(4 - successes, k) / comb(4, k) for successes in bound) / len(counts)
                for bound in (lower, upper)
            ]
            for k in (1, 2, 4)
        }
    return {
        "statuses": dict(Counter(status for status, _ in outcomes.values())),
        "pass_at_k_bounds": report,
        "all_ten_task_sensitivity_bounds": {
            channel: {
                k: [low * 9 / 10, (high * 9 + 1) / 10]
                for k, (low, high) in values.items()
            }
            for channel, values in report.items()
        },
        "confirmed_slots": sorted(slot for slot, (status, _) in outcomes.items()
                                  if status == "equivalent"),
    }


def audit(root: Path, *, score_workers: int = 0) -> dict:
    manifest, records, http, diagnostics = _read_archive(root)
    cases = _load_cases(root, manifest)
    transport, exchanges = _transport(manifest, records, http)
    variants = _compare_replays(manifest, records, cases, exchanges)
    report = {
        "archive": str(ARCHIVE),
        "transport": transport,
        "historical_scores": dict(Counter(row["status"] for row in diagnostics["scores"])),
        "repair_diagnostics": _repair_diagnostics(cases, records, exchanges),
        "initial_prompts_with_pre_or_post_annotations": sorted(
            slot for slot, steps in exchanges.items()
            if re.search(r"(?mi)^\s*(?:#\s*)?(?:pre|post)(?:\[[^\]]*\])?\s*:", steps[0][0])
        ),
        "replay_limit": (
            "Historical replies are reused only for identical prompts. Changed or new repair "
            "prompts are censored. Earlier returns are deterministic counterfactuals on the "
            "saved responses. These counts measure validation and repair behavior, not accuracy."
        ),
        "ablation": variants,
        "semantic_witnesses": _semantic_witnesses(root, manifest, variants),
    }
    if score_workers:
        report["strict_ablation"] = _strict_ablation(
            root, manifest, diagnostics, variants, score_workers,
        )
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--score-workers", type=int, default=0)
    args = parser.parse_args()
    result = audit(Path.cwd(), score_workers=args.score_workers)
    payload = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output is None:
        print(payload, end="")
    else:
        args.output.write_text(payload)
