"""Frozen case inventory and auditable group-aware dev/test split for thesis RQ1."""

from __future__ import annotations

import hashlib
import json
import random
import re
from pathlib import Path
from typing import Any

import yaml

from dualify.discovery import discover_python_cases
from dualify.gold_scoring import load_gold_benchmark

UPSTREAM_SHA = "7ffd1ae37822096d5b7b573785ee46e877903185"
DEFAULT_SEED = 20261120


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _group(stem: str) -> str:
    """Unify copies of the same upstream source function across contract frameworks."""
    for separator in ("_correct_code_", "_correct_"):
        if separator in stem:
            return stem.split(separator, 1)[1]
    return stem


def build_manifest(root: Path, *, seed: int = DEFAULT_SEED) -> dict[str, Any]:
    inputs = root / "benchmark" / "lifted_auto_eval"
    gold_dir = root / "benchmark" / "lifted"
    cases = discover_python_cases(inputs, root)
    gold = load_gold_benchmark(gold_dir)
    if len(cases) != 40 or len(gold) != 40:
        raise ValueError(f"Expected exactly 40 cases and gold contracts: {len(cases)}, {len(gold)}")
    by_stem = {contract.safe_id: contract for contract in gold.values()}
    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    for case in cases:
        source = root / case.file
        stem = source.stem
        reference = gold_dir / f"{stem}.yaml"
        if stem not in by_stem or not source.is_file() or not reference.is_file():
            raise ValueError(f"Missing unique reference/input for {case.benchmark_id}: {stem}")
        if case.benchmark_id in seen:
            raise ValueError(f"Duplicate benchmark ID: {case.benchmark_id}")
        seen.add(case.benchmark_id)
        raw_gold = yaml.safe_load(reference.read_text(encoding="utf-8"))
        text = source.read_text(encoding="utf-8")
        records.append(
            {
                "benchmark_id": case.benchmark_id,
                "input_path": source.relative_to(root).as_posix(),
                "gold_path": reference.relative_to(root).as_posix(),
                "input_sha256": _sha(source),
                "gold_sha256": _sha(reference),
                "group": _group(stem),
                "corpus": "python_by_contract" if stem.startswith("python_by_contract_") else "crosshair_examples",
                "needs_attention": bool(raw_gold.get("needs_attention", False)),
                "embedded_contract_markers": bool(re.search(r"(?m)^\s*(?:#\s*)?(?:pre|post)\s*:", text)),
                "generic_informal_spec": bool(re.match(r"(?i)^(behavior of|describe behavior)", case.informal_spec.strip())),
            }
        )
    if len(seen) != len(by_stem):
        raise ValueError("Input-to-gold mapping must be one-to-one")
    groups: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        groups.setdefault(str(record["group"]), []).append(record)
    shuffled = list(groups)
    random.Random(seed).shuffle(shuffled)

    # Group-preserving subset sum. Favor ~4 crosshair examples among the 10 dev cases.
    choices: dict[tuple[int, int], tuple[str, ...]] = {(0, 0): ()}
    for group in shuffled:
        items = groups[group]
        size = len(items)
        crosshair_count = sum(i["corpus"] == "crosshair_examples" for i in items)
        for (count, cross), picked in list(choices.items()):
            key = count + size, cross + crosshair_count
            if key[0] <= 10 and key not in choices:
                choices[key] = (*picked, group)
    possibilities = [(abs(cross - 4), picked) for (count, cross), picked in choices.items() if count == 10]
    if not possibilities:
        raise ValueError("No group-compatible 10-case dev split")
    selected = set(min(possibilities, key=lambda entry: entry[0])[1])
    dev = sorted(str(r["benchmark_id"]) for r in records if r["group"] in selected)
    test = sorted(str(r["benchmark_id"]) for r in records if r["group"] not in selected)
    if len(dev) != 10 or len(test) != 30:
        raise AssertionError("Unexpected split sizes")
    return {
        "schema": "dualify-rq1-split-v1",
        "upstream_sha": UPSTREAM_SHA,
        "seed": seed,
        "dev": dev,
        "test": test,
        "cases": sorted(records, key=lambda r: str(r["benchmark_id"])),
        "audit": {
            "group_count": len(groups),
            "embedded_contract_count": sum(bool(r["embedded_contract_markers"]) for r in records),
            "generic_spec_count": sum(bool(r["generic_informal_spec"]) for r in records),
            "needs_attention_count": sum(bool(r["needs_attention"]) for r in records),
            "crosshair_dev_count": sum(r["corpus"] == "crosshair_examples" and r["benchmark_id"] in dev for r in records),
        },
    }


def validate_manifest(root: Path, manifest: dict[str, Any]) -> None:
    if manifest != build_manifest(root, seed=int(manifest["seed"])):
        raise ValueError("Split manifest or benchmark checksums changed; stop and investigate")


def save_manifest(root: Path, target: Path, *, seed: int = DEFAULT_SEED) -> dict[str, Any]:
    data = build_manifest(root, seed=seed)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return data
