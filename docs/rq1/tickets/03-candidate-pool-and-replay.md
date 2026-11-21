# 03 — Простой sampling runner и запись четырёх независимых кандидатов

**Статус:** выполнен 2026-11-20
**Blocked by:** [02 — Native attempt](02-native-attempt-and-telemetry.md).  
**Результат:** один небольшой offline-проверяемый runner: на задачу и канал — baseline ×1, treatment ×4, сохранение отдельных кандидатов и возможность повторить **offline-анализ** по этим данным.

## Problem

Для pass@k необходимо достоверно знать, что четыре результата получены из четырёх разных полных extraction attempts, а не четырёх чтений одного cached ответа. Исходный `ReplayLLMClient(match_by_prompt=True)` способен повторять сохранённый ответ; использовать его как источник новых candidates нельзя. Ранее тикет требовал сложный crash-safe ledger, exactly-once resume и strict replay **всех внутренних LLM calls**. Для небольшого RQ1-прототипа это несоразмерно цели: достаточно сохранять реальные результаты и повторять **scoring без LLM**.

## Known facts

- Оригинальные p01/p02 создают итоговый контракт за одну full extraction attempt с возможными native repairs.
- Для каждого case/channel согласованы **четыре treatment attempts** с одинаковой initial T>0 и одна отдельная baseline attempt при T=0.
- Одинаковые финальные формулы допустимы, если действительно сделаны независимые вызовы; требование уникальности относится к **slot IDs**, а не к тексту.
- В исходном Dualify уже есть `RecordingLLMClient` и другие transcript helpers. Их можно использовать, если это сокращает реализацию, но строгая реконструкция всего выполнения extractor больше **не является обязательным результатом**.
- Replay или cached answers не считаются дополнительными live samples.

## Constraints

- Вызывай полный extractor отдельно для каждого `(case_id, channel, arm, sample_index)`. Зафиксируй уникальный slot ID и сведения о **фактическом вызове**, не только сгенерированный порядковый номер.
- Сохраняй простой JSONL или файлы на slot (выбери **один** удобный формат): slot ID, model, initial/repair temperatures, final contract / native result, статус/причину ошибки, elapsed time, наблюдаемые logical calls и исходные LLM outputs / transcript, если клиент уже их возвращает. Не создавай новый универсальный storage framework.
- Записывай результат сразу после завершения попытки; при ошибке последующие результаты не должны затирать ранее сохранённые. Для resume достаточно **пропускать проверенные completed slots** и продолжать только incomplete slots без дублирования. Полноценная транзакционная crash-recovery система не требуется.
- Проверяй полноту: на задачу/канал ровно четыре completed treatment slots и отдельный baseline. При пропуске или повторе ID — остановить campaign, а не уменьшать n/подставлять прошлый response.
- Контракты могут совпадать по тексту. Запись нескольких разных ID без нескольких реально выполненных attempts **не доказывает** независимость: в fake tests считай реальные вызовы, а в live run сохраняй доступную provenance.
- Используй существующие transcript utilities только при необходимости; `match_by_prompt=True` нельзя применять для получения «новых» samples. Offline analysis должен читать **записанные финальные кандидаты без обращения к модели**.
- Все тесты Ticket 03 работают с fake clients и локальными файлами.

## Hypotheses

- Минимальный цикл native extractor с простым файловым сохранением и проверкой полноты достаточен для достоверного RQ1 pass@k и повторного offline-scoring.
- Повторная реконструкция всех prompt hashes и внутренних repair calls через собственный strict replay verifier не добавляет необходимой для RQ1 научной информации.

## Expected outcome

- Понятная сквозная fixture для одной задачи и двух каналов: 1 baseline + 4 treatment attempts на канал, все результаты записаны в доступном для просмотра формате.
- Повторный offline-read даёт те же candidate records без API. Простая проверка отличает missing, duplicate, incomplete и ошибочно закэшированные attempts.
- Минимальная демонстрация безопасного продолжения после прерывания: completed не перезаписываются, incomplete явно видны.

## Acceptance criteria

- [ ] Fake client подтверждает **четыре отдельных вызова полного extractor** на каждый канал плюс один baseline, с уникальными IDs.
- [ ] Полные candidate records содержат достаточно результатов и provenance, чтобы позже повторить **gold scoring без повторной генерации**.
- [ ] Одинаковые текстовые outputs из отдельных фактических calls допустимы; попытка заполнить slot cached/replayed ответом не проходит проверку.
- [ ] Missing, duplicate или incomplete slot выявляется до pass@k, а завершённый invalid/degraded candidate сохраняется.
- [ ] После простого resume completed slots не меняются и не дублируются; новый вызов возможен только для incomplete.
- [ ] Один реальный пример сохранённой структуры и tests на перечисленные риски понятны; offline-read не вызывает Groq.

## Упрощение для исследовательского прототипа

**Оставить:** n=4 отдельных attempts; trace/provenance отдельного вызова; запись всех финальных outputs; проверку наличия n=4; элементарный resume; возможность повторно пересчитать оценки offline.  
**Убрать:** обязательный strict replay **внутренней** последовательности LLM calls, полное восстановление prompt hashes, проверку transcript exhaustion, универсальный append-only ledger, exactly-once event accounting и исчерпывающий набор corruption fixtures. Тотальный replay — опционален, только если уже реализован в исходном Dualify без дополнительной сложности.

**Важно:** мы ослабляем требование воспроизвести ход генерации, **не** требование получить четыре отдельных кандидата и сохранить доказательства их происхождения.

## Реализация после упрощения

- `dualify.rq1_pool.run_candidate_pool` запускает baseline и четыре treatment attempts на каждый канал, сохраняет каждый завершённый `result.json` и пропускает его при resume.
- `verify_candidate_pool` **читает финальные результаты offline**, проверяет конфигурацию, уникальность/полноту десяти слотов и записанные logical calls; больше не воспроизводит оригинальный extractor из transcript.
- Live runner принимает штатные HTTP-клиенты, в том числе под штатной recording-обёрткой. Клиенты replay и resume отклоняются. При resume сверяются модель и отпечаток endpoint. Старые пулы без отпечатка можно прочитать offline, а для новых live-слотов требуется новый каталог. `provider="fake"` используется в offline-тестах.
- При сбое `failure.json` сохраняет диагностику последней незавершённой попытки. После resume scoring читает завершённый `result.json`.
- Отдельный transcript/replay engine с внутренним восстановлением prompt hashes удалён. Сохранённый `AttemptRecord` оставляет исходный output, stage/temperature, статус и доступную provenance.
- При прерывании без завершённого `result.json` текущий slot считается incomplete и повторяется целиком; уже завершённые результаты остаются без изменений.
- Важный компромисс: восстановление **внутри** незавершённой native attempt не гарантируется, а offline gold scoring воспроизводится по завершённым результатам. Такое ограничение нужно указывать в отчёте, а не скрывать.

## Stopping criteria

**STOP**, когда одна fixture для двух каналов создаёт пять отдельно учитываемых attempts на канал, записи читаются offline, полнота/повтор IDs проверяются и простой resume сохраняет completed results. При невозможности отличить фактический вызов от cached sample — `BLOCKED`. Не реализуй универсальный transcript/replay framework, gold scorer Ticket 04 или live Groq campaign.

## Out of scope

Full strict replay всех internal calls, сложная crash-safe state machine, профессиональная система хранения, pass@k math, dev/test sampling и рефакторинг оригинальных transcript helpers.
