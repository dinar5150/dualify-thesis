# 04 — Простой offline gold scoring и pass@k-анализ

**Статус:** реализован и проверен offline.

**Blocked by:** [03 — Sampling runner](03-candidate-pool-and-replay.md).  
**Результат:** один понятный offline analyzer сохранённых финальных кандидатов, который вызывает оригинальный gold scorer, считает основные метрики RQ1 и создаёт небольшой воспроизводимый отчёт.

## Problem

Нужно вычислять pass@k без новых запросов модели, сохраняя различие между правильными, доказанно неправильными, invalid и Z3 unknown кандидатами. Неправильный denominator или оценка одной формулы без статуса solver искажает научный результат. При этом сложный reporting/telemetry framework не требуется.

## Known facts

- Dualify уже содержит `score_extraction_against_gold` и оригинальный Z3 checker; их семантика и timeout остаются неизменными.
- `equivalent=False` может означать как доказанную неэквивалентность, так и inconclusive/invalid: нужны исходный reason и diagnostics.
- Согласованы n=4, k={1,2,4}, separate spec/code, conservative pass@k, sensitivity bound для unknown, paired task-level bootstrap и descriptive T=0 baseline.
- В RQ1 нет selector и нет сравнения разных моделей; measure — наличие gold-equivalent результата среди n попыток.

## Constraints

- Читай только сохранённые **финальные** candidate records из Ticket 03; new model calls запрещены. Проверяй минимум: число/уникальность slots, принадлежность case/channel/arm и наличие финального status/result. При incomplete n=4 **не считай** итоговую метрику.
- Считай original gold equivalence **без изменения Z3**, соблюдая поддерживаемый фрагмент и timeout. Кандидаты: `equivalent`, `non_equivalent`, `invalid`, `inconclusive`; если нельзя определить категорию, `BLOCKED` с исходными diagnostics.
- Для task/channel с c подтверждёнными успехами и u unknown используй:
  - `low(k) = 1 - C(4-c,k)/C(4,k)`;
  - `high(k) = 1 - C(4-c-u,k)/C(4,k)`; `k=1,2,4`, `C(a,k)=0` при `a<k`.
- Для каждого канала отдельно: macro-average per task, `delta_4_1=low(4)-low(1)`, 95% **paired task-level bootstrap** с фиксированным seed и оговоркой, что похожие задачи могут быть зависимы; baseline T=0 — отдельная описательная статистика.
- Выводи лишь нужные показатели: per-candidate status/reason, per-task pass@k, агрегаты spec/code, uncertainty, observed attempt time/logical call counts, количество degraded/invalid/unknown, простой показатель разнообразия (unique final formulas).
- Создай обычный CSV/JSON с per-task результатами и один небольшой итоговый Markdown/JSON report. Не требуй сложных checksums всех derived artifacts, dashboard, провайдерских HTTP counters, token accounting или реестра взаимных ссылок.
- Тесты используют tiny synthetic fixtures и не вызывают Groq.

## Hypotheses

- Сохранённых final outputs достаточно, чтобы получить воспроизводимые результаты RQ1 без replay исходных генераций.
- Стандартной библиотеки и существующего gold-scoring API достаточно для простого offline анализа.

## Expected outcome

- Одна CLI/функция offline scoring: saved records → оригинальный scorer → статусы → pass@k + paired bootstrap → читаемые файлы.
- Краткий пример с входными candidate records и выходными таблицами; математические граничные тесты и проверка incomplete pools.
- Небольшой отчёт, объясняющий, что означают оценка, unknown bound и latency.

## Acceptance criteria

- [x] Fixtures: c=0 → все 0; c=1,u=0 → (0.25,0.5,1.0); c=4 → все 1; c=0,u=1 → high (0.25,0.5,1.0).
- [x] Solver `unknown` учитывается в u, invalid syntax не входит в c/u, исходные reasons доступны.
- [x] Macro-average по задачам и парный bootstrap воспроизводимы на фиксированном seed; риск зависимых похожих задач описан.
- [x] `delta_4_1` рассчитана **внутри treatment при фиксированной температуре**; T=0 baseline показан отдельно.
- [x] Пропущенный/повторный slot, неясный результат oracle или неправильный denominator дают явный отказ, а не корректно выглядящие числа.
- [x] Отчёт содержит обязательные pass@1/2/4 low/high отдельно для spec/code, delta, интервал, статус кандидатов и наблюдаемые затраты; offline повторный расчёт совпадает.
- [x] Основные tests + исходные gold/solver regression checks проходят без live API.

## Упрощение для исследовательского прототипа

**Оставить:** научно значимые метрики, origin Z3, unknown/invalid taxonomy, denominator n=4, парный confidence interval, простой отчёт и демонстрацию пересчёта без модели.  
**Убрать:** сложную систему отчётности, проверки целостности нескольких слоёв артефактов, обязательное восстановление transcript внутри analyzer, широкую telemetry и инфраструктуру метрик. Точечную проверку отсутствующих/дублированных slots сохранить.

## Stopping criteria

**STOP**, когда synthetic boundary cases и один сквозной пример saved candidates → gold scores → pass@k report проходят, независимый reviewer может воспроизвести результат одной offline-командой, а оригинальный Z3 не затронут. При неустранимо неоднозначной oracle-категории — `BLOCKED`. Не запускай dev campaign и не добавляй dashboards/selection/reporting platform.

## Out of scope

Groq sampling, выбор лучшего контракта, RQ2/RQ3, новая SMT-семантика, сложная provider telemetry и отдельный универсальный analytics framework.

## Воспроизводимый пример

Передайте по одному каталогу Ticket 03 на каждую задачу, которую нужно включить в
отчёт. В каждом каталоге лежат `pool_config.json` и десять `*/result.json`.
По умолчанию эталоны читаются из `benchmark/lifted` по точному `benchmark_id`.
Для синтетического примера тест записывает финальные records и свой gold.

```bash
demo_dir="$(mktemp -d)"
poetry run pytest -q tests/test_rq1_report.py \
  -k scores_saved_candidates_and_writes_reproducible_reports --basetemp="$demo_dir"
fixture="$demo_dir/test_scores_saved_candidates_a0"
poetry run python -m dualify.rq1_report "$fixture/increment" \
  --gold-dir "$fixture/gold" --output-dir "$demo_dir/offline"
```

| Канал | T=0 equivalent | Treatment c/u | pass@1 low/high | pass@2 low/high | pass@4 low/high | delta_4_1 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| spec | 0/1 | 1/0 | 0.25/0.25 | 0.50/0.50 | 1.00/1.00 | 0.75 |
| code | 1/1 | 4/0 | 1.00/1.00 | 1.00/1.00 | 1.00/1.00 | 0.00 |

`tasks.json` содержит оценки каждой задачи, исходные reasons и диагностику.
`summary.json` содержит макросредние, парный bootstrap и наблюдаемые затраты.
`low` учитывает доказанную эквивалентность в поддерживаемом фрагменте.
`high` дополнительно считает `solver_unknown` успехом. Разность в этом
сценарии показывает чувствительность оценки к unknown. `formula_parse_error`
классифицируется как `invalid`, если исходный scorer разбирает сам эталон.
`vacuous_equivalence` относится к `invalid`, поскольку исходная проверка
well-formedness признала сравнение непригодным.

Интервалы используют 10 000 переотборов задач с seed 20261120. Похожие задачи
могут быть зависимы, и интервалы в таком случае могут быть слишком узкими.
Сумма elapsed time отражает длительность полных attempts вместе с ожиданием и
repair. Число logical calls отражает вызовы `generate_json`. Wall-clock кампании,
физические HTTP-запросы, токены и чистая latency модели в записях недоступны.
При повторной проверке Z3 может выбрать другую SAT-модель, поэтому конкретные
значения контрпримеров в исходной диагностике могут различаться.

CLI возвращает код 1 с `BLOCKED` для несовместимых или неполных пулов
и неклассифицируемых результатов. При таком отказе файлы не записываются.
