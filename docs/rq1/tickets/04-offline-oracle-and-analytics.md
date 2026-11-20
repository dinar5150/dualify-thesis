# 04 — Превратить записанных кандидатов в проверяемый offline-отчёт RQ1

**Статус:** ready-for-agent (НЕ НАЧАТ)  
**Blocked by:** [03 — Candidate pool и strict replay](03-candidate-pool-and-replay.md).  
**Результат:** полный offline-путь без credentials — от неизменяемых candidate pools через исходный gold scoring к pass@k, uncertainty и cost.

## Problem
Один булев gold score скрывает разницу между доказанно неправильным контрактом, invalid expression и solver `unknown`. Если все false считать «неправильно», неопределённость будет искажена. Простое first-k coverage не соответствует согласованной основной метрике; а если считать четыре samples одной задачи независимыми observations, доверительные интервалы будут ошибочными.

## Known facts
- Оригинальный Dualify содержит `score_extraction_against_gold`, проверенный человеком gold corpus и Z3 equivalence checking с reason/diagnostics.
- `equivalent=False` не всегда доказывает неэквивалентность; unknown и parse failure необходимо классифицировать отдельно.
- Утверждённый estimator: n=4, k={1,2,4}, раздельные macro-averages spec/code и консервативная/unknown-sensitive границы.
- Основной эффект внутри treatment: `pass@4 − pass@1`; baseline T=0 учитывается отдельно и описательно.
- Измеренное elapsed time extractor **не равно** чистому inference latency провайдера, особенно при rate limits и retries Groq.

## Constraints
- Оценивай **только** полностью завершённые и проверенные pools из Ticket 03. При неполной campaign нужно остановить scoring, а не сокращать n.
- Используй оригинальный gold scorer; сохраняй исходные Z3 timeout, checker и семантику формального фрагмента. Сверяйся с [ограничениями оригинального метода](../../agent/KNOWN_DUALIFY_LIMITATIONS.md), фиксируй обнаруженные недостатки исходного подхода, **не модифицируя Z3**. Не добавляй LLM judge или новый oracle.
- Каждому кандидату назначь `equivalent`, `non_equivalent`, `invalid`, `inconclusive` либо `unclassified/blocked`, если источников недостаточно.
- Считай `low(k)=1−C(4−c,k)/C(4,k)` и `high(k)=1−C(4−c−u,k)/C(4,k)`. Отклоняй невозможные счётчики; сохраняй исходные diagnostics.
- Макроусредняй по task/channel; используй **парный group-aware bootstrap** с записанными seed, количеством resamples и effective groups.
- Reference truth и derived labels остаются только в offline-scoring artifacts; generation/replay не должны от них зависеть.
- Обязательно сообщай наблюдаемое время полной попытки и stage metrics. HTTP/token/inference данные провайдера указывай только при прямом наблюдении, иначе NA с объяснением.
- Все тесты полностью offline, быстрые и детерминированные.

## Hypotheses
- **Методологическая гипотеза:** исходные equivalence results можно отразить как подтверждённые успехи и честные границы неопределённости, не меняя oracle.
- **Инженерная гипотеза:** оба канала допускают один повторно используемый offline analyzer, который выявляет неполные и повреждённые pools до вычисления результатов.

## Expected outcome
- Небольшая детерминированная fixture из candidate pool создаёт per-candidate reasons, per-task low/high pass@1/2/4 и отдельные channel summaries.
- Один offline report содержит paired delta_4_1 и 95% group-aware interval, first-k diagnostic, mixed-outcome cases, распределение degraded/repair/errors, diversity и наблюдаемые расходы.
- При повторном выполнении над теми же records значения и checksums совпадают; credentials не требуются.

## Acceptance criteria
- [ ] Граничные формулы: c=0 → всё 0; c=1,u=0 → (0.25,0.5,1.0); c=4 → всё 1; c=0,u=1 → high (0.25,0.5,1.0).
- [ ] Solver `unknown` входит в u, а не в доказанную неэквивалентность; invalid syntax не включается ни в c, ни в u. Исходные reasons сохраняются.
- [ ] Все test tasks имеют одинаковый вес внутри канала; paired resampling учитывает связи задач/групп и даёт воспроизводимый 95% interval.
- [ ] Сравнение treatment k=4 vs k=1 выполняется **при одинаковой температуре**; T=0 baseline обозначается как описательный ориентир, а не чистый контроль эффекта k.
- [ ] Отчёт включает разнообразие формул, errors, количество native repairs, attempt/campaign timings, counts unknown/incomplete/NA.
- [ ] Missing slot, несовместимые counts, неклассифицируемое состояние oracle или повреждение transcript приводят к **ошибке формирования отчёта** с диагностикой, а не к правдоподобным цифрам.
- [ ] Повтор offline расчёта даёт те же числа и не вызывает сеть/модель; существующие gold/solver regression checks зелёные.

## Stopping criteria
**STOP, когда:** все граничные fixtures и один сквозной offline case проходят; report честно описывает неопределённость oracle и наличие/отсутствие telemetry; независимый reviewer может воспроизвести значения без Groq. Если нативная оценка не позволяет различать важный статус, зафиксируй `BLOCKED` и предложи лишь самое узкое улучшение наблюдаемости. Не запускай dev campaign и не настраивай метод под желаемый pass@k.

## Out of scope
Provider sampling, выбор лучшего контракта, test-set evaluation, сравнение моделей и изменение внутренней логики Z3.
