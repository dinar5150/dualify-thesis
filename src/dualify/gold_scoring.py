"""Score extracted contracts against the hand-curated gold benchmark."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]

from dualify.formula_parser import normalize_formula
from dualify.phases.p03_smt_checking import CaseSpec, check_equivalence
from dualify.relation import contract_relation
from dualify.types import ExtractionResult

DEFAULT_GOLD_DIR = Path(__file__).resolve().parents[2] / "benchmark" / "lifted"


@dataclass(frozen=True)
class GoldContract:
    benchmark_id: str
    qualname: str
    in_fragment: bool
    args: list[str]
    arg_types: dict[str, str]
    return_type: str
    domain_constraints: list[str]
    postcondition: str
    safe_id: str = ""


@dataclass
class GoldScoreResult:
    qualname: str
    gold_benchmark_id: str
    in_fragment: bool
    pre_exact: bool
    post_exact: bool
    contract_equivalent: bool
    reason: str
    pre_relation: str = ""
    post_relation: str = ""
    skipped: bool = False
    skip_reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _signature_arg_names(signature: str) -> list[str]:
    inner = signature.split("(", 1)[1].rsplit(")", 1)[0].strip()
    if not inner:
        return []
    names: list[str] = []
    for chunk in inner.split(","):
        name = chunk.strip().split(":", 1)[0].strip()
        if name:
            names.append(name)
    return names


def _normalize_pre(constraints: list[str]) -> list[str]:
    return sorted(normalize_formula(c) for c in constraints if c.strip())


def _normalize_post(postcondition: str) -> str:
    return normalize_formula(postcondition).replace(" ", "")


def pre_exact_match(generated: list[str], gold: list[str]) -> bool:
    return _normalize_pre(generated) == _normalize_pre(gold)


def post_exact_match(generated: str, gold: str) -> bool:
    return _normalize_post(generated) == _normalize_post(gold)


def _gold_formulas(record: dict[str, Any]) -> tuple[list[str], str]:
    normalized = record.get("reference_normalized")
    if isinstance(normalized, dict) and normalized.get("post") is not None:
        pre = [normalize_formula(c) for c in normalized.get("pre", []) or []]
        post = normalize_formula(str(normalized["post"]))
        return pre, post
    pre = [normalize_formula(c) for c in record.get("reference_pre", []) or []]
    post = normalize_formula(str(record.get("reference_post", "") or ""))
    return pre, post


def _load_arg_types(record: dict[str, Any]) -> dict[str, str]:
    raw = record.get("arg_types")
    if isinstance(raw, dict) and raw:
        return {str(k): str(v) for k, v in raw.items()}
    signature = str(record.get("signature", ""))
    parsed: dict[str, str] = {}
    inner = signature.split("(", 1)[1].rsplit(")", 1)[0].strip() if "(" in signature else ""
    for chunk in inner.split(","):
        chunk = chunk.strip()
        if not chunk or ":" not in chunk:
            continue
        name, type_name = chunk.split(":", 1)
        parsed[name.strip()] = type_name.strip()
    return parsed


def load_gold_benchmark(gold_dir: Path = DEFAULT_GOLD_DIR) -> dict[str, GoldContract]:
    """Load gold contracts keyed by ``benchmark_id``.

    Keying by ``benchmark_id`` (which is globally unique) rather than
    ``qualname`` is essential: five function names (e.g. ``double``, ``swap``,
    ``next_departure``) recur across the PEP316/icontract/correct-vs-buggy
    variants. Keying by qualname silently collapsed those collisions and
    dropped 5 of the 40 records.
    """
    contracts: dict[str, GoldContract] = {}
    if not gold_dir.is_dir():
        return contracts
    for path in sorted(gold_dir.glob("*.yaml")):
        record = yaml.safe_load(path.read_text())
        if not isinstance(record, dict):
            continue
        qualname = str(record.get("qualname", "") or "").strip()
        if not qualname:
            continue
        pre, post = _gold_formulas(record)
        arg_types = _load_arg_types(record)
        benchmark_id = str(record.get("benchmark_id", qualname))
        contracts[benchmark_id] = GoldContract(
            benchmark_id=benchmark_id,
            qualname=qualname,
            in_fragment=bool(record.get("in_fragment", True)),
            args=_signature_arg_names(str(record.get("signature", ""))),
            arg_types=arg_types,
            return_type=str(record.get("return_type", "")),
            domain_constraints=pre,
            postcondition=post,
            safe_id=path.stem,
        )
    return contracts


def build_gold_lookup(contracts: dict[str, GoldContract]) -> dict[str, GoldContract]:
    """Map safe-ids, benchmark-ids, and (best-effort) short names to contracts.

    ``safe_id`` (the gold YAML file stem) and ``benchmark_id`` are unique and
    always win. Short-name/qualname keys are ambiguous across variants, so they
    are only filled via ``setdefault`` and must never override a unique key.
    """
    lookup: dict[str, GoldContract] = {}
    for contract in contracts.values():
        if contract.safe_id:
            lookup[contract.safe_id] = contract
        lookup[contract.benchmark_id] = contract
    for contract in contracts.values():
        tail = contract.benchmark_id.split("::")[-1]
        lookup.setdefault(contract.qualname, contract)
        lookup.setdefault(tail, contract)
        if "." in contract.qualname:
            lookup.setdefault(contract.qualname.split(".")[-1], contract)
    return lookup


def lookup_gold_contract(
    benchmark_id: str,
    contracts: dict[str, GoldContract],
    lookup: dict[str, GoldContract] | None = None,
    *,
    source_file: str = "",
) -> GoldContract | None:
    index = lookup if lookup is not None else build_gold_lookup(contracts)
    # Prefer the unambiguous file-stem match (eval `.py` stem == gold YAML stem).
    if source_file:
        stem = Path(source_file).stem
        if stem in index:
            return index[stem]
    if benchmark_id in index:
        return index[benchmark_id]
    tail = benchmark_id.split("::")[-1]
    if tail in index:
        return index[tail]
    for key, contract in index.items():
        if key.endswith(f".{tail}") or key.endswith(f"::{tail}"):
            return contract
    return None


def _extraction_from_gold(gold: GoldContract) -> ExtractionResult:
    return ExtractionResult(
        benchmark_id=gold.benchmark_id,
        args=list(gold.args),
        return_type=gold.return_type,
        domain_constraints=list(gold.domain_constraints),
        postcondition=gold.postcondition,
        confidence="gold",
        notes="reference contract",
    )


def _case_spec_for_gold(benchmark_id: str, gold: GoldContract) -> CaseSpec:
    return CaseSpec(
        benchmark_id=benchmark_id,
        arg_types=dict(gold.arg_types),
        return_type=gold.return_type,
    )


def score_extraction_against_gold(
    *,
    case_spec: CaseSpec,
    gold: GoldContract,
    extraction: ExtractionResult,
) -> GoldScoreResult:
    if not gold.in_fragment:
        return GoldScoreResult(
            qualname=gold.qualname,
            gold_benchmark_id=gold.benchmark_id,
            in_fragment=False,
            pre_exact=False,
            post_exact=False,
            contract_equivalent=False,
            reason="skipped_out_of_fragment",
            skipped=True,
            skip_reason="out_of_fragment",
        )

    pre_exact = pre_exact_match(extraction.domain_constraints, gold.domain_constraints)
    post_exact = post_exact_match(extraction.postcondition, gold.postcondition)

    gold_extraction = _extraction_from_gold(gold)
    smt = check_equivalence(case_spec, gold_extraction, extraction)
    relation = contract_relation(case_spec, gold_extraction, extraction)
    # Both checks produce sound proofs when they return unsat, but Z3 may
    # return unknown for a different encoding of the same obligation.
    # Reconcile proven results. Never promote a candidate on `unknown` alone.
    pre_relation = relation["pre"]
    post_relation = relation["post"]
    equivalent = smt.equivalent
    reason = smt.reason
    if equivalent:
        if pre_relation in {"generated_stronger", "generated_weaker", "incomparable"} or post_relation in {
            "generated_stronger", "generated_weaker", "incomparable"
        }:
            # Contradictory *definite* SMT evidence must not count as success.
            equivalent = False
            reason = "oracle_conflict"
        else:
            pre_relation = "equivalent"
            post_relation = "equivalent"
    elif (
        reason == "solver_unknown"
        and pre_relation == "equivalent"
        and post_relation == "equivalent"
        and (smt.diagnostics or {}).get("post_well_formedness") == "ok"
    ):
        # Two proved implications in each direction establish equivalence,
        # even if the XOR query returned unknown.
        equivalent = True
        reason = "equivalent_via_implications"
    elif reason == "solver_unknown" and (
        pre_relation in {"generated_stronger", "generated_weaker", "incomparable"}
        or post_relation in {"generated_stronger", "generated_weaker", "incomparable"}
    ):
        # A model for either failed implication proves non-equivalence,
        # even if the aggregate XOR check was inconclusive.
        reason = "non_equivalent_via_implications"
    return GoldScoreResult(
        qualname=gold.qualname,
        gold_benchmark_id=gold.benchmark_id,
        in_fragment=True,
        pre_exact=pre_exact,
        post_exact=post_exact,
        contract_equivalent=equivalent,
        reason=reason,
        pre_relation=pre_relation,
        post_relation=post_relation,
    )


def score_case_against_gold(
    *,
    benchmark_id: str,
    spec_extraction: ExtractionResult,
    code_extraction: ExtractionResult,
    gold_by_qualname: dict[str, GoldContract],
    gold_lookup: dict[str, GoldContract] | None = None,
    source_file: str = "",
) -> dict[str, Any] | None:
    gold = lookup_gold_contract(
        benchmark_id, gold_by_qualname, gold_lookup, source_file=source_file
    )
    if gold is None:
        return None
    case_spec = _case_spec_for_gold(benchmark_id, gold)
    spec_score = score_extraction_against_gold(
        case_spec=case_spec, gold=gold, extraction=spec_extraction
    )
    code_score = score_extraction_against_gold(
        case_spec=case_spec, gold=gold, extraction=code_extraction
    )
    return {
        "qualname": gold.qualname,
        "gold_benchmark_id": gold.benchmark_id,
        "in_fragment": gold.in_fragment,
        "spec": spec_score.to_dict(),
        "code": code_score.to_dict(),
    }


def summarize_gold_scores(case_gold_scores: list[dict[str, Any] | None]) -> dict[str, Any]:
    """Aggregate per-case gold scores into run-level counters."""
    spec_pre = spec_post = spec_contract = 0
    code_pre = code_post = code_contract = 0
    scorable = skipped_no_gold = skipped_fragment = 0
    spec_parse = code_parse = 0
    reasons_spec: dict[str, int] = {}
    reasons_code: dict[str, int] = {}
    spec_pre_rel: dict[str, int] = {}
    spec_post_rel: dict[str, int] = {}
    code_pre_rel: dict[str, int] = {}
    code_post_rel: dict[str, int] = {}

    for entry in case_gold_scores:
        if entry is None:
            skipped_no_gold += 1
            continue
        if not entry.get("in_fragment", True):
            skipped_fragment += 1
            continue
        scorable += 1
        spec = entry["spec"]
        code = entry["code"]
        if spec.get("pre_exact"):
            spec_pre += 1
        if spec.get("post_exact"):
            spec_post += 1
        if spec.get("contract_equivalent"):
            spec_contract += 1
        if code.get("pre_exact"):
            code_pre += 1
        if code.get("post_exact"):
            code_post += 1
        if code.get("contract_equivalent"):
            code_contract += 1
        sr = str(spec.get("reason", "")).split(":", 1)[0]
        cr = str(code.get("reason", "")).split(":", 1)[0]
        reasons_spec[sr] = reasons_spec.get(sr, 0) + 1
        reasons_code[cr] = reasons_code.get(cr, 0) + 1
        if sr == "formula_parse_error":
            spec_parse += 1
        if cr == "formula_parse_error":
            code_parse += 1

        def _bump(table: dict[str, int], value: Any) -> None:
            if value:
                key = str(value)
                table[key] = table.get(key, 0) + 1

        _bump(spec_pre_rel, spec.get("pre_relation"))
        _bump(spec_post_rel, spec.get("post_relation"))
        _bump(code_pre_rel, code.get("pre_relation"))
        _bump(code_post_rel, code.get("post_relation"))

    return {
        "scorable_cases": scorable,
        "skipped_no_gold": skipped_no_gold,
        "skipped_out_of_fragment": skipped_fragment,
        "spec_pre_exact": spec_pre,
        "spec_post_exact": spec_post,
        "spec_contract_equivalent": spec_contract,
        "code_pre_exact": code_pre,
        "code_post_exact": code_post,
        "code_contract_equivalent": code_contract,
        "spec_parse_errors": spec_parse,
        "code_parse_errors": code_parse,
        "spec_reason_distribution": reasons_spec,
        "code_reason_distribution": reasons_code,
        "spec_pre_relation_distribution": spec_pre_rel,
        "spec_post_relation_distribution": spec_post_rel,
        "code_pre_relation_distribution": code_pre_rel,
        "code_post_relation_distribution": code_post_rel,
    }


def score_run_results(
    run: dict[str, Any],
    gold_dir: Path = DEFAULT_GOLD_DIR,
) -> dict[str, Any]:
    """Attach gold scores to an existing run report (no LLM calls)."""
    gold_by_qualname = load_gold_benchmark(gold_dir)
    gold_lookup = build_gold_lookup(gold_by_qualname)
    scored_cases: list[dict[str, Any]] = []
    gold_entries: list[dict[str, Any] | None] = []

    for case in run.get("results", []):
        if not isinstance(case, dict):
            continue
        spec_payload = case.get("spec_to_logic", {})
        code_payload = case.get("code_to_logic", {})
        if not isinstance(spec_payload, dict) or not isinstance(code_payload, dict):
            gold_entries.append(None)
            continue
        spec_ex = ExtractionResult(
            benchmark_id=str(case.get("benchmark_id", "")),
            args=list(spec_payload.get("args", [])),
            return_type=str(spec_payload.get("return_type", "")),
            domain_constraints=list(spec_payload.get("domain_constraints", [])),
            postcondition=str(spec_payload.get("postcondition", "")),
            confidence=str(spec_payload.get("confidence", "")),
            notes=str(spec_payload.get("notes", "")),
        )
        code_ex = ExtractionResult(
            benchmark_id=str(case.get("benchmark_id", "")),
            args=list(code_payload.get("args", [])),
            return_type=str(code_payload.get("return_type", "")),
            domain_constraints=list(code_payload.get("domain_constraints", [])),
            postcondition=str(code_payload.get("postcondition", "")),
            confidence=str(code_payload.get("confidence", "")),
            notes=str(code_payload.get("notes", "")),
        )
        gold_entry = score_case_against_gold(
            benchmark_id=str(case.get("benchmark_id", "")),
            spec_extraction=spec_ex,
            code_extraction=code_ex,
            gold_by_qualname=gold_by_qualname,
            gold_lookup=gold_lookup,
            source_file=str(case.get("file", "")),
        )
        gold_entries.append(gold_entry)
        if gold_entry is not None:
            case_copy = dict(case)
            case_copy["gold_scoring"] = gold_entry
            scored_cases.append(case_copy)
        else:
            scored_cases.append(case)

    summary = summarize_gold_scores(gold_entries)
    return {
        **run,
        "results": scored_cases if scored_cases else list(run.get("results", [])),
        "summary": {
            **(run.get("summary", {}) if isinstance(run.get("summary"), dict) else {}),
            "gold_scoring": summary,
        },
    }
