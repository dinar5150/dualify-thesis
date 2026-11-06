"""Build the frozen, annotation-free inputs for the 40-case gold benchmark.

Usage: python scripts/prepare_clean_benchmark.py
"""

from __future__ import annotations

import ast
import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "benchmark" / "lifted_auto_eval"
CLEAN = ROOT / "benchmark" / "lifted_auto_eval_clean"
GOLD = ROOT / "benchmark" / "lifted"
FORMAL = re.compile(r"^\s*(?:pre|post|inv|invariant|requires|ensures)\s*:", re.I)


def git_blob_sha(content: bytes) -> str:
    """Git's content hash, usable for source, cleaned input, and gold files."""
    return hashlib.sha1(b"blob " + str(len(content)).encode() + b"\0" + content).hexdigest()


def strip_formal_docstrings(source: str) -> str:
    """Remove PEP316 pre/post directive lines only from function docstrings."""
    tree = ast.parse(source)
    lines = source.splitlines(keepends=True)
    remove: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) or not node.body:
            continue
        doc = node.body[0]
        if not (
            isinstance(doc, ast.Expr)
            and isinstance(doc.value, ast.Constant)
            and isinstance(doc.value.value, str)
        ):
            continue
        for line_no in range(doc.lineno + 1, doc.end_lineno):
            if FORMAL.match(lines[line_no - 1]):
                remove.add(line_no)

    cleaned = "".join(line for i, line in enumerate(lines, 1) if i not in remove)
    for node in ast.walk(ast.parse(cleaned)):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            doc = ast.get_docstring(node) or ""
            if any(FORMAL.match(line) for line in doc.splitlines()):
                raise ValueError("Unsupported inline or continued formal docstring directive")
    return cleaned


def prepare() -> None:
    originals = sorted(SOURCE.glob("*.py"))
    gold_files = {p.stem: p for p in GOLD.glob("*.yaml")}
    stems = {p.stem for p in originals}
    if not originals or stems != set(gold_files):
        raise ValueError("Source and gold file stems differ; inspect the benchmark")
    CLEAN.mkdir(parents=True, exist_ok=True)
    existing = {p.stem for p in CLEAN.glob("*.py")}
    if existing - stems:
        raise ValueError("Unexpected Python files in clean benchmark")

    manifest = {"version": 1, "source": "lifted_auto_eval", "gold": "lifted", "cases": []}
    for source_path in originals:
        original_bytes = source_path.read_bytes()
        clean_bytes = strip_formal_docstrings(original_bytes.decode("utf-8")).encode("utf-8")
        gold_bytes = gold_files[source_path.stem].read_bytes()
        (CLEAN / source_path.name).write_bytes(clean_bytes)
        manifest["cases"].append({
            "stem": source_path.stem,
            "source_blob": git_blob_sha(original_bytes),
            "clean_blob": git_blob_sha(clean_bytes),
            "gold_blob": git_blob_sha(gold_bytes),
        })
    (CLEAN / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    prepare()
