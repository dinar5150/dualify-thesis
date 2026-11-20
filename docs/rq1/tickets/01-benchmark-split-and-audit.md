# 01 — Зафиксировать оригинальный benchmark и провести аудит утечек

**Статус:** `SPLIT_FROZEN` (выполнен 2026-11-20)
**Blocked by:** нет — первый незаблокированный тикет.  
**Результат:** воспроизводимый и проверенный manifest 10 dev / 30 test и полный аудит рисков 40 оригинальных примеров benchmark, без подключения к Groq.

## Problem
Оригинальный benchmark Dualify содержит всего 40 задач с gold и несколько родственных вариантов функций. Случайное деление может поместить почти одинаковые примеры одновременно в dev и test. Встроенные формальные аннотации или слабые неформальные описания усложняют трактовку «правильного extraction». Исследование нельзя начинать без зафиксированной и проверяемой границы датасета.

## Known facts
- Upstream commit `7ffd1ae37822096d5b7b573785ee46e877903185` содержит 40 Python-входов `lifted_auto_eval` и 40 соответствующих human-confirmed gold YAML в `lifted`.
- В некоторых группах есть варианты одной исходной функции; для группировки нужна проверка идентичности и семантического/source сходства, не только совпадения имён.
- Gold корректен в рамках поддерживаемого фрагмента логики; входной код может содержать аннотации, похожие на контракты.
- Решения Q1, Q3, Q4 требуют неизменяемых входов и group-aware split 10 dev / 30 held-out test.

## Constraints
- Сохраняй оригинальные benchmark inputs и gold **байт-в-байт**; запиши checksums.
- Каждый уникальный benchmark ID присутствует ровно один раз и только в одном split. Все близкие примеры относятся к одной группе. По возможности сохраняй баланс происхождения корпуса и `needs_attention`; отклонения объясняй.
- Сформируй split **до** любых live LLM-экспериментов. Не используй качество генерации для назначения групп.
- Проверь все задачи на formal pre/post, слишком общие informal specs, сходство исходников, необычное качество reference и возможное попадание gold в generation inputs. Результат аудита не даёт права исключать/переписывать задачу.
- Gold text не попадает в prompts и runtime generation inputs. Код старых веток форка не является источником реализации.
- Тикет представляет **offline vertical slice**: одна воспроизводимая команда создаёт manifest и audit с однозначным результатом проверки.

## Hypotheses
- **Инженерная гипотеза:** можно построить стабильный split и полный аудит для исходного benchmark, не разделяя родственные функции.
- Если точное 10/30 несовместимо с группировкой, сообщи конкретные конфликтующие группы и остановись для отдельного решения; не ослабляй правила молча.

## Expected outcome
- Детерминированный manifest с seed, правилом групп, всеми 40 IDs, provenance, group memberships, назначением 10/30, input/gold hashes и результатом проверки.
- Case-level leakage/quality audit, суммарные счётчики и явные флаги вместо необъяснённых оценок.
- Повторяемая offline-команда с positive- и negative-тестами некорректного manifest.
- Наблюдаемый статус `SPLIT_FROZEN`, если все проверки пройдены, либо `BLOCKED` с точной причиной.

## Acceptance criteria
- [x] На чистом checkout ветки от оригинального upstream повторное выполнение с фиксированным seed воспроизводит тот же manifest и hashes.
- [x] Ровно 40 уникальных задач; ровно 10 dev / 30 test; никакая группа не разделена; каждому входу соответствует ровно один gold.
- [x] Аудит содержит case-level аннотации, группы похожих функций, слабые описания, происхождение и quality metadata.
- [x] Тесты отвергают отсутствующие/повторные IDs, drift source, неправильные hashes и близкие функции по разные стороны split.
- [x] При выполнении **ноль** live LLM requests; исходные benchmark/gold не изменяются.
- [x] В verification record записаны команды, версии, checksums и объяснения компромиссов.

## Frozen artifacts

- Manifest: [`benchmark/rq1/manifest.json`](../../../benchmark/rq1/manifest.json)
- Audit: [`benchmark/rq1/audit.json`](../../../benchmark/rq1/audit.json)
- Group registry: [`benchmark/rq1_groups.yaml`](../../../benchmark/rq1_groups.yaml)
- Reproduction notes: [`benchmark/rq1/README.md`](../../../benchmark/rq1/README.md)
- Verification record: [`docs/rq1/TICKET_01_VERIFICATION.md`](../TICKET_01_VERIFICATION.md)

## Stopping criteria
**STOP, когда:** manifest стабилен и проверен, аудит покрывает все 40 задач, positive/negative тесты проходят и результат отмечен как `SPLIT_FROZEN`. Если группировка или split несовместимы с требованиями, остановись со статусом `BLOCKED` и доказательствами. **Не переходи автоматически** к model sampling, подбору модели, refactoring или Ticket 02.

## Out of scope
Groq credentials, sampling модели, pass@k, изменение gold formulas и решения по held-out результатам.
