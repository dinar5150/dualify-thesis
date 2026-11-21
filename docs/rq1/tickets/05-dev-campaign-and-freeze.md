# 05 — Провести полный dev, независимый review, заморозить конфигурацию и остановиться

**Статус:** BLOCKED. Дневной лимит Groq, 65/100 завершённых слотов. [Отчёт и freeze](../TICKET_05_DEV.md)

**Blocked by:** [04 — Offline oracle и аналитика](04-offline-oracle-and-analytics.md).  
**Результат:** воспроизводимая **dev campaign на 10 задачах**, независимая проверка, документированные дефекты, заморозка методологии и итоговый статус `READY FOR HELD-OUT TEST` / `BLOCKED`.

## Problem
Unit tests проверяют интерфейсы, но не устойчивость реальной кампании через Groq. Dev gate нужен, чтобы один раз убедиться в корректности измерения и остановиться до test. Полное ревью всех внутренних функций не является целью исследования. Rate limits Groq Free Tier и transport behavior способны искажать latency и классификацию ошибок.

## Known facts
- Утверждённый split содержит ровно **10 dev** задач. Для каждой: baseline и четыре treatment attempts по двум каналам, всего **100 полных extraction attempt slots**.
- Точный Qwen model ID и рекомендованная положительная температура зависят от доступной модели Groq; они должны быть зафиксированы перед live stage, без молчаливой замены.
- Штатный repair может делать дополнительные LLM calls; transport retries увеличивают число физических HTTP requests.
- RQ1 использует подтверждённую gold equivalence, conservative pass@k, unknown bounds, attempt elapsed time и полную provenance ошибок.
- Согласованный Definition of Done останавливает разработку **перед** held-out кампанией на 30 задачах.

## Constraints
- Начинай тикет после успешного завершения Tickets 01–04. Перед dev-прогоном проверь все offline-тесты, исходную конфигурацию и объявленный бюджет API.
- На preflight сохрани model ID, mode, endpoint, T>0 из подходящих рекомендаций, baseline/repair T=0, timeout/retry/rate-limit policy, полный dependency/source manifest и checksums. Неполные параметры блокируют запуск.
- Выполни объявленный полный dev plan с конечным бюджетом API; по достижении cap/exhaustion остановись. Не делай дополнительные попытки ради «красивых» метрик.
- Сохраняй реальные Groq statuses/bodies; различай out-of-service/429/5xx, ошибки генерируемого JSON и постоянные ошибки client config. Resume только неполных инфраструктурных slots. Latency учитывает ожидания/backoff.
- Проверь, что все сохранённые attempts действительно получены отдельными model calls, у каждого есть ID и итоговый контракт, offline scoring работает без LLM, а gold не использовался в generation. Кратко проверь риски benchmark и известные ограничения Dualify.
- Исправляй только объективные correctness/integrity дефекты, выявленные на dev. Документируй изменения, повторяй относящиеся к проблеме тесты и оправданные dev checks; обновляй [KNOWN_BUGS.md](../../agent/KNOWN_BUGS.md). Не подгоняй качество, не добавляй temperature sweep, дополнительные k или fine-tuning.
- При доступности используй **независимого reviewer/subagent** для двух осей — Standards и Spec. Основное внимание удели научным инвариантам: (1) отдельные attempts; (2) отсутствие gold leakage; (3) сохранение оригинального Z3; (4) правильный pass@k/unknown. Остальную реализацию достаточно проверить тестами и кратким обзором изменённых модулей. Если subagent недоступен, явно укажи это и проведи два раздельных review-прохода.
- После выполнения зафиксируй code revision, manifest, run configuration и scoring rules. Held-out test не входит в этот тикет.

## Hypotheses
- **Инженерная гипотеза:** все 100 slots можно завершить, проверить и воспроизвести в пределах бюджета без неклассифицированных ошибок.
- **Исследование на dev (exploratory):** pool показывает, действительно ли pipeline измеряет вариативность корректности. Значения dev pass@k **не финальный результат** и не цель оптимизации.

## Expected outcome
- Простые сохранённые records всех 100 attempts: slots, фактические вызовы, результаты/ошибки, доступные prompts/outputs, настройки, время и scores. Missing/ambiguous слоты ведут к `BLOCKED`, а не к видимости завершённого эксперимента. Не нужен универсальный immutable event ledger.
- Offline reproduction и по каждому каналу pass@1/2/4 bounds, delta, 95% intervals, latency/quality/diversity summary и limitations.
- Короткий независимый review по Standards и Spec с акцентом на научные инварианты, критические замечания и подтверждение исправлений. Пример «один input → сохранённые candidates → оригинальный Z3 → pass@k» для объяснения исследователю.
- Frozen pre-test manifest и явное решение `READY FOR HELD-OUT TEST` или `BLOCKED`.

## Acceptance criteria
- [ ] Offline tests и существующий regression suite пройдены **до** первого live API call.
- [ ] Model, численная T, endpoint, limits, hashes, revisions source/dependencies и split зафиксированы до первого dev запроса.
- [ ] Ровно 100 planned dev slots завершены либо запуск явно `BLOCKED` с доказательствами недостающих слотов; все 10×2 treatment pools имеют n=4.
- [ ] У каждого completed slot есть provenance и oracle status; ambiguous provider errors, missing calls и replay mismatches не учитываются скрытно как ошибки контракта.
- [ ] Повторный **offline scoring** по сохранённым final candidates воспроизводит pass@k reports без API; полный strict replay внутренних LLM calls не требуется.
- [ ] Review по Standards и Spec проверяет четыре критических инварианта (отдельные attempts, отсутствие gold leakage, исходный Z3, правильные pass@k/unknown) и известные ограничения метрик. Агент показывает один понятный сквозной пример результата.
- [ ] Blocking findings закрыты точечными тестами и записаны в bug register; необязательные косметические и архитектурные замечания не приводят к расширению scope.
- [ ] Freeze manifest содержит точные commit и configuration, итоговый gate verdict; обращений к test и просмотра test outcomes не было.

## Упрощение для исследовательского прототипа

**Оставить:** один реальный dev run, n=4, freeze перед test, воспроизводимый offline scoring, проверку четырёх научных инвариантов и короткую демонстрацию pipeline.  
**Убрать:** обязательную реконструкцию всех внутренних LLM calls, подробный line-by-line human review, многократные раунды независимых ревью без критических дефектов, промышленную систему observability и optimisation по dev pass@k. Review должен помогать **понять результат**, а не превращаться в аудит каждой вспомогательной функции.

## Stopping criteria
**STOP сразу, когда** завершены 100 dev attempts, offline scoring и критические проверки, blocking review findings закрыты, а frozen настройки подтверждают `READY FOR HELD-OUT TEST`. Если quota, конфигурация или неоднозначная ошибка не дают выполнить критерии в пределах заявленного бюджета, **STOP со статусом `BLOCKED`** и описанием недостающих данных. Сообщи gate status и запроси отдельное разрешение на Ticket 06; **никогда не запускай его автоматически**. Никакой бесконечной полировки, sweeps или «ещё одного» post-dev sample.

## Out of scope
Полный 30-case test, выводы по held-out эффектам, дополнительные модели и изменения ради максимального dev pass@k.
