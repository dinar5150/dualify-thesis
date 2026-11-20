# 03 — Пул из четырёх кандидатов с безопасным resume и strict replay

**Статус:** выполнен 2026-11-20
**Blocked by:** [02 — Native attempt и telemetry](02-native-attempt-and-telemetry.md).  
**Результат:** сквозной **offline** пример: один benchmark case, baseline и четыре отдельно идентифицируемых treatment attempts для каждого канала; запись результатов, безопасный resume и проверка через replay.

## Problem
Повтор одинакового prompt не доказывает независимость sampling, если нет подтверждения отдельной live attempt для каждого кандидата. Original prompt-matching transcript replay может вернуть старый ответ, когда сохранённые responses закончились. Сбои и перезапуски также создают недостающие или дублированные slots. Без надёжного candidate ledger pass@k нельзя считать достоверным.

## Known facts
- Оригинальные `RecordingLLMClient`, `ReplayLLMClient`, `ResumingLLMClient` реализуют transcript с prompt hashes и replay.
- В `ReplayLLMClient(match_by_prompt=True)` последний записанный ответ может выдаваться повторно после исчерпания подходящих записей; это **не новый sample**.
- Upstream strict sequential replay проверяет упорядоченные prompt hashes, но native extractors могут перехватывать replay exceptions; нужна внешняя проверка завершённости.
- Утверждённый эксперимент требует ровно четыре treatment **slots** на case/channel плюс один baseline; одинаковые формулы допустимы.
- Infrastructure recovery допускается только в рамках **того же** incomplete slot; успешно завершённые, но неправильные slots не заменяются.

## Constraints
- Назначь стабильные IDs вида (task, channel, arm, sample-index) и отдельный порядок logical calls внутри каждого slot.
- Сохраняй raw prompts/temperatures, final native extraction traces и достаточные данные для offline verification без API credentials.
- Переиспользуй исходные transcript interfaces там, где это безопасно; enforce strict ordered replay, соответствие prompt hashes, cardinality calls и exhaustion **над** extraction layer.
- Не создавай samples из replay/cache. Одинаковые формулы считаются разными кандидатами **только при наличии записей об отдельных фактических attempts**.
- Используй append-only запись либо atomic slots; crash не должен незаметно дублировать готовый slot или завершать повреждённую запись.
- Missing/exhausted infrastructure slots остаются incomplete. Сохраняй успешный префикс и retry history; n не сокращается.
- Тикет должен запускаться с fake responses, **без Groq**.

## Hypotheses
- **Инженерная гипотеза:** candidate ledger и внешний replay verifier позволяют использовать исходные transcript возможности и обеспечивают exactly-once **учёт слотов** после crash/resume без обещания детерминированного live sampling.

## Expected outcome
- Воспроизводимая fixture: одна задача, оба канала, по одному baseline и четырём treatment slots, уникальные IDs и связанные extraction/transcript records.
- Успешный offline replay восстанавливает те же финальные candidate records и доказывает, что все записанные LLM calls израсходованы.
- Negative-тесты: отсутствующий/лишний LLM record, неправильный prompt hash, повтор последнего ответа, повторный slot ID, interrupted slot и resume этого же slot.

## Acceptance criteria
- [x] Для каждого case/channel присутствуют четыре **завершённых уникальных slot IDs** и отдельный baseline; одинаковый текст кандидатов не уменьшает счётчик.
- [x] Каждый completed slot связан с реальными записанными model responses (или fake responses в тестах) и ровно одним финальным native extractor result.
- [x] Strict replay проверяет порядок prompts, temperatures, counts, identity responses и полное exhaustion; все повреждённые fixtures приводят к fail-closed.
- [x] Replay mismatch, перехваченный native extractor, всё равно обнаруживается внешней проверкой и не превращается в допустимый degraded candidate.
- [x] Replay и offline resume не вызывают сеть.
- [x] Interrupted slot можно возобновить на том же месте, сохранив completed slots; повторный resume идемпотентен в тестируемых случаях.
- [x] Invalid/degraded, но завершённый model output сохраняется; неустранённая инфраструктурная ошибка блокирует campaign.
- [x] Оригинальные transcript regression tests проходят.

## Реализация

- `dualify.rq1_pool.run_candidate_pool` создаёт фиксированные baseline/treatment slots для
  каналов spec и code, сохраняет отдельный transcript каждого slot и атомарно публикует
  только завершённый `result.json`.
- При повторном запуске завершённые slots пропускаются, а незавершённый slot использует
  сохранённый transcript prefix и дописывает только недостающие вызовы. Незавершённая
  инфраструктурная ошибка останавливает campaign на текущем slot.
- `verify_candidate_pool` последовательно воспроизводит pool offline и проверяет slot IDs,
  prompt hashes, температуры, порядок и количество вызовов, identity ответов, финальный
  native result и полное расходование transcript.

## Stopping criteria
**STOP, когда:** offline fixture для двух каналов подтверждает полные n=4 pools, resume и strict replay без сети, а все corruption fixtures стабильно проваливаются. Если точную идентичность нельзя доказать по transcript, укажи `BLOCKED`; не ослабляй контроль молча. Не генерируй реальные candidates и не реализуй gold scoring сверх заглушки интерфейса.

## Out of scope
Gold oracle pass@k, доверительные интервалы, настоящие Groq campaigns и общие рефакторинги transcript.
