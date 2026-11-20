from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, cast

import yaml

UPSTREAM_COMMIT = "7ffd1ae37822096d5b7b573785ee46e877903185"
TICKET_BASE_COMMIT = "eca293043c4c2b1d9615e556a7829e3c739044e4"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _tree_sha256(paths: list[Path]) -> str:
    digest = hashlib.sha256()
    for path in sorted(paths, key=lambda item: item.name):
        digest.update(path.name.encode("utf-8"))
        digest.update(b"\x00")
        digest.update(path.read_bytes())
        digest.update(b"\x00")
    return digest.hexdigest()


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _load_groups(
    source_root: Path, benchmark_ids: set[str]
) -> tuple[dict[str, str], dict[str, Any]]:
    path = source_root / "benchmark" / "rq1_groups.yaml"
    config = cast(dict[str, Any], yaml.safe_load(path.read_text(encoding="utf-8")))
    assignments: dict[str, str] = {}
    for group_id, group in config["groups"].items():
        for benchmark_id in group["members"]:
            if benchmark_id not in benchmark_ids:
                raise ValueError(f"group {group_id} references unknown ID: {benchmark_id}")
            if benchmark_id in assignments:
                raise ValueError(f"duplicate group assignment: {benchmark_id}")
            assignments[benchmark_id] = str(group_id)
    for benchmark_id in benchmark_ids - assignments.keys():
        assignments[benchmark_id] = f"singleton:{benchmark_id}"
    return assignments, config


def _load_audit_rules(source_root: Path) -> dict[str, Any]:
    path = source_root / "benchmark" / "rq1_audit_rules.yaml"
    return cast(dict[str, Any], yaml.safe_load(path.read_text(encoding="utf-8")))


def _select_dev_groups(
    group_stats: dict[str, tuple[int, int, int]],
    seed: int,
    target_crosshair: int,
    target_attention: int,
) -> set[str]:
    ordered = sorted(
        group_stats,
        key=lambda group_id: hashlib.sha256(f"{seed}:{group_id}".encode()).hexdigest(),
    )
    choices: dict[tuple[int, int, int], tuple[str, ...]] = {(0, 0, 0): ()}
    for group_id in ordered:
        size, crosshair_count, attention_count = group_stats[group_id]
        for state, selected in list(choices.items()):
            total, crosshair_total, attention_total = state
            new_total = total + size
            new_state = (
                new_total,
                crosshair_total + crosshair_count,
                attention_total + attention_count,
            )
            if new_total <= 10 and new_state not in choices:
                choices.setdefault(new_state, (*selected, group_id))
    candidates = [
        (state, selected) for state, selected in choices.items() if state[0] == 10
    ]
    if not candidates:
        sizes = ", ".join(
            f"{name}={stats[0]}" for name, stats in sorted(group_stats.items())
        )
        raise ValueError(f"BLOCKED: no exact group-aware 10/30 split; group sizes: {sizes}")
    _, selected = min(
        candidates,
        key=lambda item: (
            abs(item[0][1] - target_crosshair)
            + abs(item[0][2] - target_attention),
            abs(item[0][1] - target_crosshair),
            abs(item[0][2] - target_attention),
            hashlib.sha256(f"{seed}:{','.join(sorted(item[1]))}".encode()).hexdigest(),
        ),
    )
    return set(selected)


def _formal_annotations(source: str) -> list[dict[str, Any]]:
    annotations: list[dict[str, Any]] = []
    pattern = re.compile(r"^(?:\s*#\s*)?(pre|post(?:\[[^]]+\])?)\s*:", re.IGNORECASE)
    directive = re.compile(r"^\s*#\s*(crosshair|icontract|deal)\s*:", re.IGNORECASE)
    for line_number, line in enumerate(source.splitlines(), start=1):
        stripped = line.strip()
        match = pattern.match(stripped)
        directive_match = directive.match(line)
        if match:
            annotations.append(
                {"kind": match.group(1).lower(), "line": line_number, "text": stripped}
            )
        elif directive_match:
            annotations.append(
                {"kind": "formal_directive", "line": line_number, "text": stripped}
            )
    return annotations


def _informal_spec_quality(
    benchmark_id: str, audit_rules: dict[str, Any]
) -> dict[str, Any]:
    reasons = list(audit_rules["too_general_informal_specs"].get(benchmark_id, []))
    return {"too_general": bool(reasons), "reasons": reasons}


def _gold_quality(gold: dict[str, Any]) -> dict[str, Any]:
    reference_formulas = [
        *(str(item) for item in gold.get("reference_pre", [])),
        str(gold.get("reference_post", "")),
    ]
    reference_text = " ".join(reference_formulas)
    notes = str(gold.get("notes", ""))
    limitations: list[str] = []
    if gold.get("needs_attention", False):
        limitations.append("needs_attention")
    if not str(gold.get("profile", "")).strip():
        limitations.append("empty_profile")
    if re.search(r"\b(?:ForAll|Exists)\b", reference_text):
        limitations.append("quantified_reference")
    partial_markers = (
        "not expressible",
        "only captures",
        "only the",
        "under-approximation",
        "does not assert",
        "weakened",
    )
    if any(marker in notes.lower() for marker in partial_markers):
        limitations.append("partial_reference")
    return {
        "status": gold.get("status"),
        "in_fragment": bool(gold.get("in_fragment", False)),
        "needs_attention": bool(gold.get("needs_attention", False)),
        "reference_pre_count": len(gold.get("reference_pre", [])),
        "reference_post_present": bool(str(gold.get("reference_post", "")).strip()),
        "profile_present": bool(str(gold.get("profile", "")).strip()),
        "limitations": limitations,
    }


def _build_benchmark(source_root: Path, seed: int) -> tuple[dict[str, Any], dict[str, Any]]:
    input_dir = source_root / "benchmark" / "lifted_auto_eval"
    gold_dir = source_root / "benchmark" / "lifted"
    input_paths = sorted(input_dir.glob("*.py"))
    gold_files = sorted(gold_dir.glob("*.yaml"))
    gold_paths = {path.stem: path for path in gold_files}
    input_stems = {path.stem for path in input_paths}
    gold_stems = set(gold_paths)
    if len(input_paths) != 40 or len(gold_files) != 40:
        raise ValueError(
            f"expected 40 inputs and 40 gold files, got {len(input_paths)} and {len(gold_files)}"
        )
    if input_stems != gold_stems:
        raise ValueError(
            "input/gold stem mismatch: "
            f"missing_gold={sorted(input_stems - gold_stems)}, "
            f"missing_input={sorted(gold_stems - input_stems)}"
        )
    audit_rules = _load_audit_rules(source_root)
    source_lock = audit_rules["source_lock"]
    if source_lock.get("upstream_commit") != UPSTREAM_COMMIT:
        raise ValueError("audit source lock does not reference the frozen upstream commit")
    input_tree_sha256 = _tree_sha256(input_paths)
    gold_tree_sha256 = _tree_sha256(gold_files)
    if input_tree_sha256 != source_lock["input_tree_sha256"]:
        raise ValueError(
            "source drift: input corpus does not match immutable upstream lock "
            f"{source_lock['input_tree_sha256']}"
        )
    if gold_tree_sha256 != source_lock["gold_tree_sha256"]:
        raise ValueError(
            "source drift: gold corpus does not match immutable upstream lock "
            f"{source_lock['gold_tree_sha256']}"
        )

    rows: list[dict[str, Any]] = []
    source_by_id: dict[str, str] = {}
    gold_by_id: dict[str, dict[str, Any]] = {}
    for input_path in input_paths:
        gold_path = gold_paths[input_path.stem]
        gold = cast(dict[str, Any], yaml.safe_load(gold_path.read_text(encoding="utf-8")))
        benchmark_id = str(gold["benchmark_id"])
        if benchmark_id in gold_by_id:
            raise ValueError(f"duplicate benchmark ID in gold: {benchmark_id}")
        source_by_id[benchmark_id] = input_path.read_text(encoding="utf-8")
        gold_by_id[benchmark_id] = gold
        rows.append(
            {
                "benchmark_id": benchmark_id,
                "group_id": benchmark_id,
                "input_path": input_path.relative_to(source_root).as_posix(),
                "input_sha256": _sha256(input_path),
                "gold_path": gold_path.relative_to(source_root).as_posix(),
                "gold_sha256": _sha256(gold_path),
            }
        )

    reviewed_ids = set(audit_rules["too_general_informal_specs"])
    unknown_reviewed_ids = reviewed_ids - set(gold_by_id)
    if unknown_reviewed_ids:
        raise ValueError(
            f"audit rules reference unknown benchmark IDs: {sorted(unknown_reviewed_ids)}"
        )

    group_assignments, group_config = _load_groups(
        source_root, {row["benchmark_id"] for row in rows}
    )
    group_stats: dict[str, tuple[int, int, int]] = {}
    for row in rows:
        group_id = group_assignments[row["benchmark_id"]]
        row["group_id"] = group_id
        size, crosshair_count, attention_count = group_stats.get(group_id, (0, 0, 0))
        group_stats[group_id] = (
            size + 1,
            crosshair_count + int(row["benchmark_id"].startswith("crosshair_examples::")),
            attention_count
            + int(bool(gold_by_id[row["benchmark_id"]].get("needs_attention", False))),
        )
    target_crosshair = round(sum(stats[1] for stats in group_stats.values()) * 10 / 40)
    target_attention = round(sum(stats[2] for stats in group_stats.values()) * 10 / 40)
    dev_groups = _select_dev_groups(
        group_stats, seed, target_crosshair, target_attention
    )
    for row in rows:
        row["split"] = "dev" if row["group_id"] in dev_groups else "test"

    audits: list[dict[str, Any]] = []
    for row in rows:
        benchmark_id = row["benchmark_id"]
        source = source_by_id[benchmark_id]
        gold = gold_by_id[benchmark_id]
        group_id = row["group_id"]
        group_definition = group_config["groups"].get(group_id)
        group_reason = (
            group_definition["reason"]
            if group_definition is not None
            else "No close or dependent function was identified in the 40-case corpus."
        )
        annotations = _formal_annotations(source)
        reference_formulas = [
            *(str(item) for item in gold.get("reference_pre", [])),
            str(gold.get("reference_post", "")),
        ]
        exact_matches = [formula for formula in reference_formulas if formula and formula in source]
        audits.append(
            {
                "benchmark_id": benchmark_id,
                "group_id": group_id,
                "group_reason": group_reason,
                "provenance": {
                    "source_corpus": benchmark_id.split("::", 1)[0],
                    "input_path": row["input_path"],
                    "gold_path": row["gold_path"],
                    "pairing_rule": "identical filesystem-safe benchmark stem",
                },
                "embedded_formal_annotations": annotations,
                "gold_text_in_generation_input": {
                    "exact_match": bool(exact_matches),
                    "matched_reference_formulas": exact_matches,
                },
                "informal_spec_quality": _informal_spec_quality(benchmark_id, audit_rules),
                "gold_quality": _gold_quality(gold),
            }
        )

    readme = (gold_dir / "README.md").read_text(encoding="utf-8")
    declared_match = re.search(r"Flagged `needs_attention`.*?\|\s*(\d+)", readme)
    declared_attention = int(declared_match.group(1)) if declared_match else None
    observed_attention = sum(case["gold_quality"]["needs_attention"] for case in audits)
    audit_summary = {
        "case_count": len(audits),
        "embedded_formal_annotation_case_count": sum(
            bool(case["embedded_formal_annotations"]) for case in audits
        ),
        "exact_gold_text_overlap_case_count": sum(
            case["gold_text_in_generation_input"]["exact_match"] for case in audits
        ),
        "weak_informal_spec_case_count": sum(
            case["informal_spec_quality"]["too_general"] for case in audits
        ),
        "needs_attention_count": observed_attention,
        "gold_readme_needs_attention_declared": declared_attention,
        "gold_readme_count_discrepancy": declared_attention != observed_attention,
        "source_corpus_counts": {
            corpus: sum(case["provenance"]["source_corpus"] == corpus for case in audits)
            for corpus in sorted({case["provenance"]["source_corpus"] for case in audits})
        },
    }

    manifest: dict[str, Any] = {
        "schema_version": 1,
        "status": "SPLIT_FROZEN",
        "seed": seed,
        "split_rule": {
            "algorithm": "group subset dynamic programming with proportional-balance objective",
            "dev_size": 10,
            "test_size": 30,
            "balance_targets": {
                "crosshair_examples": target_crosshair,
                "needs_attention": target_attention,
            },
            "balance_achieved": {
                "crosshair_examples": sum(
                    row["split"] == "dev"
                    and row["benchmark_id"].startswith("crosshair_examples::")
                    for row in rows
                ),
                "needs_attention": sum(
                    row["split"] == "dev"
                    and bool(gold_by_id[row["benchmark_id"]].get("needs_attention", False))
                    for row in rows
                ),
            },
            "seed_role": "SHA-256 tie-break among equally balanced exact group subsets",
            "selected_dev_groups": sorted(dev_groups),
            "compromise": "Targets are rounded corpus proportions; both targets are achieved.",
        },
        "grouping_rules": group_config["grouping_rules"],
        "group_definitions": group_config["groups"],
        "provenance": {
            "upstream_commit": UPSTREAM_COMMIT,
            "ticket_base_commit": TICKET_BASE_COMMIT,
            "input_root": "benchmark/lifted_auto_eval",
            "gold_root": "benchmark/lifted",
            "group_config": "benchmark/rq1_groups.yaml",
            "group_config_sha256": _sha256(source_root / "benchmark" / "rq1_groups.yaml"),
            "audit_rules": "benchmark/rq1_audit_rules.yaml",
            "audit_rules_sha256": _sha256(
                source_root / "benchmark" / "rq1_audit_rules.yaml"
            ),
            "input_tree_sha256": input_tree_sha256,
            "gold_tree_sha256": gold_tree_sha256,
            "pairing_rule": "input .py and gold .yaml share the same filesystem-safe stem",
        },
        "cases": rows,
    }
    audit: dict[str, Any] = {
        "schema_version": 1,
        "summary": audit_summary,
        "cases": audits,
    }
    return manifest, audit


def verify_benchmark(*, source_root: Path, output_dir: Path, seed: int) -> None:
    manifest_path = output_dir / "manifest.json"
    audit_path = output_dir / "audit.json"
    if not manifest_path.is_file() or not audit_path.is_file():
        raise ValueError("manifest.json and audit.json must both exist")
    actual_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    actual_audit = json.loads(audit_path.read_text(encoding="utf-8"))
    expected_manifest, expected_audit = _build_benchmark(source_root, seed)

    actual_cases = actual_manifest.get("cases", [])
    actual_ids = [case.get("benchmark_id") for case in actual_cases]
    if len(actual_ids) != len(set(actual_ids)):
        raise ValueError("duplicate benchmark IDs in manifest")
    expected_by_id = {case["benchmark_id"]: case for case in expected_manifest["cases"]}
    actual_by_id = {case.get("benchmark_id"): case for case in actual_cases}
    if set(actual_by_id) != set(expected_by_id):
        missing = sorted(set(expected_by_id) - set(actual_by_id))
        extra = sorted(set(actual_by_id) - set(expected_by_id), key=str)
        raise ValueError(f"missing/extra benchmark IDs: missing={missing}, extra={extra}")

    for benchmark_id, expected in expected_by_id.items():
        actual = actual_by_id[benchmark_id]
        if actual.get("input_sha256") != expected["input_sha256"]:
            raise ValueError(f"source drift or corrupted input hash: {benchmark_id}")
        if actual.get("gold_sha256") != expected["gold_sha256"]:
            raise ValueError(f"gold drift or corrupted gold hash: {benchmark_id}")

    if actual_manifest != expected_manifest:
        raise ValueError("manifest metadata, grouping, or split differs from the frozen result")
    if actual_audit != expected_audit:
        raise ValueError("audit differs from the source-derived result")


def prepare_benchmark(*, source_root: Path, output_dir: Path, seed: int) -> None:
    manifest, audit = _build_benchmark(source_root, seed)
    _write_json(output_dir / "manifest.json", manifest)
    _write_json(output_dir / "audit.json", audit)
    verify_benchmark(source_root=source_root, output_dir=output_dir, seed=seed)

