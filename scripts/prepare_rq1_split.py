"""Create the fixed offline RQ1 dev/test manifest."""

import argparse
import hashlib
import json
import random
import sys
from pathlib import Path

import yaml  # type: ignore[import-untyped]

SEED = 20261120
INPUT_DIR = Path("benchmark/lifted_auto_eval")
GOLD_DIR = Path("benchmark/lifted")
OUTPUT_PATH = Path("docs/rq1/benchmark-manifest.json")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _build_manifest() -> dict[str, object]:
    # Связываем код и gold по имени файла без расширения.
    # Например, example.py соответствует example.yaml.
    input_paths = {path.stem: path for path in INPUT_DIR.glob("*.py")}
    gold_paths = {path.stem: path for path in GOLD_DIR.glob("*.yaml")}
    if set(input_paths) != set(gold_paths):
        raise ValueError("input/gold filenames differ")
    # В оригинальном benchmark ровно 40 пар. Потерю файла нельзя скрыть сплитом.
    if len(input_paths) != 40:
        raise ValueError(f"expected 40 input/gold pairs, found {len(input_paths)}")

    # Настоящий ID задачи берём из gold YAML, а не придумываем по имени файла.
    records: list[tuple[str, Path, Path]] = []
    for stem in sorted(input_paths):
        gold_path = gold_paths[stem]
        gold = yaml.safe_load(gold_path.read_text(encoding="utf-8"))
        records.append((str(gold["benchmark_id"]), input_paths[stem], gold_path))

    benchmark_ids = [benchmark_id for benchmark_id, _, _ in records]
    if len(set(benchmark_ids)) != 40:
        raise ValueError("duplicate benchmark_id in gold files")

    # Это весь split: сортируем ID, одинаково перемешиваем при одном seed
    # и отдаём первые 10 в dev. Остальные 30 автоматически станут test.
    shuffled_ids = sorted(benchmark_ids)
    random.Random(SEED).shuffle(shuffled_ids)
    dev_ids = set(shuffled_ids[:10])

    # Записываем задачи в стабильном порядке, а не в порядке перемешивания.
    # Split хранится меткой в JSON: копировать входные файлы по папкам не нужно.
    cases = []
    for benchmark_id, input_path, gold_path in records:
        cases.append(
            {
                "benchmark_id": benchmark_id,
                "split": "dev" if benchmark_id in dev_ids else "test",
                "input_path": input_path.as_posix(),
                "gold_path": gold_path.as_posix(),
                # Хеши позволяют обнаружить, что код или gold изменился после split.
                "input_sha256": _sha256(input_path),
                "gold_sha256": _sha256(gold_path),
            }
        )

    return {
        "seed": SEED,
        "cases": cases,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    # Каждый запуск заново вычисляет ожидаемый manifest из текущих файлов.
    # В режиме --check сравниваем его с сохранённым JSON, ничего не перезаписывая.
    try:
        expected = _build_manifest()
        if args.check:
            actual = json.loads(args.output.read_text(encoding="utf-8"))
            if actual != expected:
                raise ValueError("manifest does not match current benchmark files")
            print(f"Verified {args.output}")
        else:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(
                json.dumps(expected, indent=2, ensure_ascii=False), encoding="utf-8"
            )
            print(f"Wrote {args.output}")
    except (KeyError, OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
