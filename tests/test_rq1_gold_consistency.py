"""A single generated contract must have a single gold label within RQ1."""

from __future__ import annotations

from dataclasses import dataclass

from dualify.rq1_sampling import GoldScoreCache


def test_same_contract_is_scored_once_across_stages_and_channels(monkeypatch):
    from dualify import gold_scoring

    @dataclass
    class FakeReference:
        benchmark_id: str
        arg_types: dict[str, str]
        return_type: str
        domain_constraints: list[str]
        postcondition: str

    refs = {
        "pep.py": FakeReference("PEP316::double", {"items": "List[str]"}, "List[str]", [], "Length(ret) == Length(items) * 2"),
        "icon.py": FakeReference("icontract::double", {"items": "List[str]"}, "List[str]", [], "ret == Concat(items, items)"),
    }

    def fake_lookup(benchmark_id, gold, *, source_file=""):
        return gold.get(source_file)

    calls = []

    def fake_score(*, case_spec, gold, extraction):
        calls.append((gold.benchmark_id, extraction.postcondition))
        verdict = len(calls) % 2 == 1  # Deliberately inconsistent fake solver.
        return FakeResult(
            gold_benchmark_id=gold.benchmark_id,
            contract_equivalent=verdict,
            reason="equivalent_no_mismatch" if verdict else "solver_unknown",
            post_relation="equivalent" if verdict else "undetermined",
        )

    @dataclass
    class FakeResult:
        gold_benchmark_id: str
        contract_equivalent: bool
        reason: str
        post_relation: str

    monkeypatch.setattr(gold_scoring, "lookup_gold_contract", fake_lookup)
    monkeypatch.setattr(gold_scoring, "score_extraction_against_gold", fake_score)

    case1 = {"benchmark_id": "double", "file": "pep.py", "arg_types": {"items": "List[str]"}, "return_type": "List[str]"}
    case2 = {"benchmark_id": "double", "file": "icon.py", "arg_types": {"items": "List[str]"}, "return_type": "List[str]"}
    cache = GoldScoreCache(refs)
    results = [cache.score(case1, "ret == Concat(items, items)", []) for _ in range(8)]
    assert all(score == results[0] for score in results)
    assert len(calls) == 1
    assert cache.hits == 7

    # Two different benchmark variants of the same Python function name are not merged.
    result2 = cache.score(case2, "ret == Concat(items, items)", [])
    assert result2["gold_benchmark_id"] == "icontract::double"
    assert len(calls) == 2

    # A changed formula must receive a new score.
    cache.score(case1, "ret == items", [])
    assert len(calls) == 3

    # Returning a cached score must not hand out its mutable internal dictionary.
    results[0]["reason"] = "tampered"
    assert cache.score(case1, "ret == Concat(items, items)", [])["reason"] != "tampered"
