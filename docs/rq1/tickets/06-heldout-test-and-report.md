# 06 — Один зафиксированный held-out RQ1 experiment и результаты для диплома

**Статус:** ready-for-agent, **ЯВНЫЙ ЗАПРЕТ ЗАПУСКА БЕЗ РАЗРЕШЕНИЯ**  
**Blocked by:** [05 — Dev campaign и freeze](05-dev-campaign-and-freeze.md) **И новое явное разрешение пользователя после dev gate**.  
**Результат:** одна полная held-out оценка 30 задач (spec + code), воспроизводимые отчёты и обоснованный вывод по дипломному RQ1.

## Problem
Одних dev results недостаточно для научного вывода. Но преждевременный test или изменение методики после просмотра результатов превращают held-out данные в tuning set. Финальный прогон должен использовать отдельно разрешённый зафиксированный протокол и честно показывать неопределённость и ограничения провайдера.

## Known facts
- По Ticket 01 в test назначаются ровно **30 задач**; всего **300 planned full extractor attempts**: 30 × 2 канала × (1 baseline + 4 treatment).
- Утверждён комбинаторный pass@k для n=4, k={1,2,4}; основной эффект — разница pass@4 − pass@1 **внутри sampling arm** для spec и code отдельно.
- Baseline T=0 описательный; вывод о чистом эффекте k допустим только для сравнения внутри treatment с одной температурой.
- Gold equivalence ограничена оригинальным формальным фрагментом. Solver unknown и invalid требуют отдельных категорий.
- Test требует отдельного разрешения после Ticket 05; изменения протокола по test outcomes запрещены.

## Constraints
- Не начинай без **актуального письменного согласия пользователя**, прямо относящегося к Ticket 06 и утверждённому frozen code/config/manifest из Ticket 05.
- Проверь source hashes, assignment cases и provider/model settings по freeze. Нельзя скрыто менять модель, подбирать температуру, исправлять benchmark, менять retry policy, oracle или k.
- Выполни только объявленные n=4 + baseline на case/channel. При неустранимой инфраструктурной/config ошибке остановись; resume разрешён в пределах исходной same-slot policy. Любое необходимое отклонение задокументируй и согласуй **до** повторного запуска.
- Во время extraction test gold недоступен. Candidate pool фиксируется и записывается **до** offline scoring.
- Отчёт включает полную taxonomy успехов/unknown/invalid/errors, conservative pass@k и optimistic unknown bounds, paired uncertainty, diversity/repair, latency и ограничения policy провайдера и корпусов.
- Не меняй протокол и не делай дополнительные live attempts, чтобы улучшить test coverage. Новые идеи можно оформить как будущие работы RQ2/RQ3, но не реализовывать здесь.

## Hypotheses
- **Описательный научный вопрос:** можно оценить размер oracle coverage gain от k=1 к k=4 на held-out задачах вместе с uncertainty и дополнительной стоимостью. Монотонность pass@k следует из математики и сама по себе не доказывает новизну.
- **Целостность:** одну frozen test campaign можно воспроизвести и проверить offline без доступа к Groq.

## Expected outcome
- Ровно 300 зафиксированных и проверенных held-out slots либо прозрачный отчёт `INCOMPLETE` (никакой фиктивной полноты).
- Воспроизводимый отчёт: отдельно spec/code pass@1/2/4 low/high, delta_4_1, 95% paired task-level intervals, first-k diagnostic и baseline comparison.
- Письменный вывод для диплома: effect size, uncertainty, задачи, где дополнительный sampling помог найти правильный кандидат, затраты/latency, provider constraints и threats to validity.
- Доказательства отсутствия post-hoc tuning и соблюдения freeze.

## Acceptance criteria
- [ ] Отдельное письменное разрешение и соответствие frozen hashes/config зафиксированы **до первого test request**.
- [ ] Есть все 30 ожидаемых test case IDs; ровно 300 planned full attempt slots завершены либо эксперимент отмечен `INCOMPLETE` с прозрачными diagnostics.
- [ ] Все treatment pools имеют n=4; strict replay проверяет cardinality запросов/ответов, prompt settings и identities кандидатов.
- [ ] Oracle scores сохраняют различие unknown/invalid; offline analytics не обращается к live API.
- [ ] Оба канала содержат pass@1/2/4, per-task results, low/high, paired delta с 95% intervals, first-k diagnostic и число задач с оговоркой о возможной зависимости близких примеров.
- [ ] В отчёте явно различаются performance costs, observed attempt latency, доступная HTTP telemetry, retries/rate-limit ожидания и отсутствующие метрики.
- [ ] Дипломный вывод не содержит необоснованных утверждений о causal effects, selection или полной Python-семантике; test results не повлекли неутверждённой настройки.
- [ ] Review report и инструкции воспроизведения указывают точные неизменяемые artifacts.

## Stopping criteria
**STOP, когда:** единственная frozen held-out campaign, offline reproduction и RQ1 report удовлетворяют acceptance criteria. Если обязательный slot не завершить в пределах заявленных лимитов, **STOP со статусом `INCOMPLETE`**, сохрани audit trail и запросив новое решение. Не повторяй run и не меняй протокол самостоятельно, не начинай RQ2 и не занимайся полировкой после обоснованного вывода.

## Out of scope
Неутверждённые test reruns, поиск гиперпараметров модели, новые методы sampling, RQ2 selection и RQ3 fine-tuning.
