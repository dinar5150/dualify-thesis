# Ticket 01 — воспроизведение и риски benchmark

## Воспроизведение

Создать зафиксированный manifest:

```bash
poetry run python scripts/prepare_rq1_split.py
```

Проверить committed manifest без перезаписи:

```bash
poetry run python scripts/prepare_rq1_split.py --check
```

Обе команды работают offline. Seed `20261120`, пути и SHA-256 всех 40 input/gold
пар записаны в [`benchmark-manifest.json`](benchmark-manifest.json).

## Подтверждённые риски и ограничения

- Семь PEP316 input cases содержат встроенные строки `pre:`/`post:`. Например,
  `arith.py_swap` прямо описывает перестановку элементов, а `unit_normalize`
  содержит ограничения размера, dtype, диапазона и результата. Эти подсказки
  остаются частью оригинального generation input и не удаляются.
- В `crosshair_examples::PEP316::correct_code::showcase.py::even_fibb`
  gold-precondition `n >= 0` дословно присутствует в input. Других дословных
  совпадений полных `reference_pre`/`reference_post` формул не обнаружено.
- Похожие функции не группируются по утверждённому протоколу. В текущем split
  PEP316-вариант `swap` находится в dev, а icontract-вариант — в test. Поэтому
  30 held-out задач нельзя трактовать как полностью независимые примеры;
  возможная зависимость раскрывается как угроза валидности.
- Gold-контракты являются эталонами внутри поддерживаемого Dualify fragment, а
  не полными спецификациями поведения Python.

Gold-текст не используется для назначения split и не передаётся в prompts.
Исходные input и gold не изменялись.

## Проверки

- `poetry run pytest -q tests/test_rq1_split.py tests/test_gold_scoring.py` —
  `12 passed`.
- `poetry run mypy src tests` — success, 37 source files.
- `poetry run pytest -q` — `105 passed, 1 skipped`.
- Ruff для изменённых Python-файлов — passed. Полный `poetry run ruff check .`
  на исходном `main` сообщает 172 ранее существовавших нарушения в benchmark/
  result fixtures и старых scripts; они не относятся к Ticket 01.
- Две генерации во временных каталогах byte-identical и совпадают с committed
  manifest (`SHA-256 394535502580d91c2d5363c165b3a6f6319cff15185bce952e6962384c392bfa`).
- `git diff --exit-code origin/main -- benchmark/lifted_auto_eval benchmark/lifted`
  завершился без diff: исходные 40 input и 40 gold не изменены.
