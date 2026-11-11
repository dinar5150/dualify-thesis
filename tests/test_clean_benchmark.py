"""Check that the pinned 40-case inputs expose no formal contract directives."""

from __future__ import annotations

import ast
import json
from pathlib import Path

from dualify.discovery import discover_python_cases
from dualify.gold_scoring import load_gold_benchmark, lookup_gold_contract
from scripts.prepare_clean_benchmark import (
    CLEAN,
    FORMAL,
    GOLD,
    ROOT,
    SOURCE,
    git_blob_sha,
    strip_formal_docstrings,
)


def test_sanitizer_only_changes_docstring_directives() -> None:
    source = '''# pre: leave this source comment unchanged

def f(x: int) -> int:
    """A normal description.

    pre: x > 0
    post: _ == x
    """
    post = "post: normal Python string"
    return x
'''
    cleaned = strip_formal_docstrings(source)
    assert "    pre: x > 0" not in cleaned
    assert "    post: _ == x" not in cleaned
    assert '# pre: leave this source comment unchanged' in cleaned
    assert 'post = "post: normal Python string"' in cleaned
    ast.parse(cleaned)


def test_clean_benchmark_is_complete_and_pinned() -> None:
    manifest = json.loads((CLEAN / "manifest.json").read_text(encoding="utf-8"))
    records = manifest["cases"]
    stems = [record["stem"] for record in records]
    assert manifest["version"] == 1
    assert manifest["source"] == "lifted_auto_eval"
    assert manifest["gold"] == "lifted"
    assert len(records) == 40  # This frozen evaluation version deliberately has 40 tasks.
    assert stems == sorted(set(stems))
    assert set(stems) == {p.stem for p in SOURCE.glob("*.py")}
    assert set(stems) == {p.stem for p in CLEAN.glob("*.py")}
    assert set(stems) == {p.stem for p in GOLD.glob("*.yaml")}

    gold = load_gold_benchmark()
    cases = discover_python_cases(CLEAN, ROOT)
    assert len(cases) == len(records)
    assert len(gold) == len(records)
    case_by_stem = {Path(case.file).stem: case for case in cases}
    for record in records:
        stem = record["stem"]
        original = (SOURCE / f"{stem}.py").read_bytes()
        cleaned = (CLEAN / f"{stem}.py").read_bytes()
        reference = (GOLD / f"{stem}.yaml").read_bytes()
        assert git_blob_sha(original) == record["source_blob"]
        assert git_blob_sha(cleaned) == record["clean_blob"]
        assert git_blob_sha(reference) == record["gold_blob"]
        assert cleaned.decode("utf-8") == strip_formal_docstrings(original.decode("utf-8"))
        assert ast.parse(original).body and ast.parse(cleaned).body
        case = case_by_stem[stem]
        assert not any(FORMAL.match(line) for line in case.informal_spec.splitlines())
        assert not any(FORMAL.match(line) for line in case.function_source.splitlines())
        assert lookup_gold_contract(case.benchmark_id, gold, source_file=case.file) is not None


def test_dev_small_uses_the_same_clean_inputs() -> None:
    dev = ROOT / "benchmark" / "dev_small"
    for path in dev.glob("*.py"):
        assert path.read_bytes() == (CLEAN / path.name).read_bytes()
