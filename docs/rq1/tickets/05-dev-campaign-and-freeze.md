# 05 — Провести полный dev, независимый review, заморозить конфигурацию и остановиться

**Статус:** ready-for-agent (НЕ НАЧАТ; live dev не разрешён текущей задачей по документации)  
**Blocked by:** [04 — Offline oracle и аналитика](04-offline-oracle-and-analytics.md).  
**Результат:** воспроизводимая **dev campaign на 10 задачах**, независимая проверка, документированные дефекты, заморозка методологии и итоговый статус `READY FOR HELD-OUT TEST` / `BLOCKED`.

## Problem
Unit tests проверяют интерфейсы, но не устойчивость реальной кампании через Groq. Без ограниченного dev gate агент может бесконечно улучшать метрики либо преждевременно перейти к test и испортить независимость оценки. Rate limits Groq Free Tier и transport behavior способны искажать latency и классификацию ошибок.

## Known facts
- Утверждённый split содержит ровно **10 dev** задач. Для каждой: baseline и четыре treatment attempts по двум каналам, всего **100 полных extraction attempt slots**.
- Точный Qwen model ID и рекомендованная положительная температура зависят от доступной модели Groq; они должны быть зафиксированы перед live stage, без молчаливой замены.
- Штатный repair может делать дополнительные LLM calls; transport retries увеличивают число физических HTTP requests.
- RQ1 использует подтверждённую gold equivalence, conservative pass@k, unknown bounds, attempt elapsed time и полную provenance ошибок.
- Согласованный Definition of Done останавливает разработку **перед** held-out кампанией на 30 задачах.

## Constraints
- Начинай тикет только после зелёных Tickets 01–04 и явного запуска будущего implementation/dev этапа пользователем. **Текущая задача по переводу документации не разрешает live API calls.**
- На preflight сохрани model ID, mode, endpoint, T>0 из подходящих рекомендаций, baseline/repair T=0, timeout/retry/rate-limit policy, полный dependency/source manifest и checksums. Неполные параметры блокируют запуск.
- Выполни объявленный полный dev plan с конечным бюджетом API; по достижении cap/exhaustion остановись. Не делай дополнительные попытки ради «красивых» метрик.
- Сохраняй реальные Groq statuses/bodies; различай out-of-service/429/5xx, ошибки генерируемого JSON и постоянные ошибки client config. Resume только неполных инфраструктурных slots. Latency учитывает ожидания/backoff.
- Проверь strict replay, offline scoring и leakage audit. Сверь поведение с известными багами.
- Исправляй только объективные correctness/integrity дефекты, выявленные на dev. Документируй изменения, повторяй относящиеся к проблеме тесты и оправданные dev checks; обновляй [KNOWN_BUGS.md](../../agent/KNOWN_BUGS.md). Не подгоняй качество, не добавляй temperature sweep, дополнительные k или fine-tuning.
- При доступности используй **независимого reviewer/subagent**, передав ему frozen protocol, diff, fixtures и artifacts. Если недоступен, явно сообщи ограничение и проведи отдельный структурированный review.
- После выполнения зафиксируй code revision, manifest, run configuration и scoring rules. Held-out test не входит в этот тикет.

## Hypotheses
- **Инженерная гипотеза:** все 100 slots можно завершить, проверить и воспроизвести в пределах бюджета без неклассифицированных ошибок.
- **Исследование на dev (exploratory):** pool показывает, действительно ли pipeline измеряет вариативность корректности. Значения dev pass@k **не финальный результат** и не цель оптимизации.

## Expected outcome
- Полный неизменяемый dev ledger на 100 slots: prompts, outputs, extraction traces, scores и retries. Missing/ambiguous слоты ведут к `BLOCKED`, а не к видимости успешного завершения.
- Offline reproduction и по каждому каналу pass@1/2/4 bounds, delta, 95% intervals, latency/quality/diversity summary и limitations.
- Один независимый review report: критические замечания, доказательства нужных fixes, regression tests и rechecks.
- Frozen pre-test manifest и явное решение `READY FOR HELD-OUT TEST` или `BLOCKED`.

## Acceptance criteria
- [ ] Offline tests и существующий regression suite пройдены **до** первого live API call.
- [ ] Model, численная T, endpoint, limits, hashes, revisions source/dependencies и split зафиксированы до первого dev запроса.
- [ ] Ровно 100 planned dev slots завершены либо запуск явно `BLOCKED` с доказательствами недостающих слотов; все 10×2 treatment pools имеют n=4.
- [ ] У каждого completed slot есть provenance и oracle status; ambiguous provider errors, missing calls и replay mismatches не учитываются скрытно как ошибки контракта.
- [ ] Offline replay воспроизводит final candidate records и pass@k reports без API.
- [ ] Review проверяет независимость sampling slots, native repair fidelity, трактовку oracle unknown, leakage, статистику и ограничения metrics/latency.
- [ ] Blocking findings закрыты точечными тестами и записаны в bug register; остальные замечания задокументированы без расширения scope.
- [ ] Freeze manifest содержит точные commit и configuration, итоговый gate verdict; обращений к test и просмотра test outcomes не было.

## Stopping criteria
**STOP сразу, когда** dev завершён и проверен, blocking review findings закрыты, а frozen artifacts подтверждают `READY FOR HELD-OUT TEST`. Если quota, конфигурация или неоднозначная ошибка не дают выполнить критерии в пределах заявленного бюджета, **STOP со статусом `BLOCKED`** и описанием недостающих данных. Сообщи gate status и запроси отдельное разрешение на Ticket 06; **никогда не запускай его автоматически**. Никакой бесконечной полировки, sweeps или «ещё одного» post-dev sample.

## Out of scope
Полный 30-case test, выводы по held-out эффектам, дополнительные модели и изменения ради максимального dev pass@k.
