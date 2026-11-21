# RQ1 Ticket 05 — dev campaign и freeze

## Запуск и воспроизведение

Из корня чистого checkout на зафиксированной ревизии:

```bash
poetry run pytest -q
poetry run python scripts/prepare_rq1_split.py --check
poetry run python -m dualify.rq1_dev results/rq1-dev-2026-11-22
```

Команда использует `GROQ_API_KEY` из окружения или локального `.env` и
проверяет доступность модели по `GET /models`. До запроса записывает
`preflight.json` с ревизией, версиями, SHA-256, split и 100 slot IDs.
Конфигурация привязана к каталогу кампании. Повтор команды с тем же каталогом
пропускает завершённые слоты и допускает продолжение после классифицированного
инфраструктурного сбоя. При оборванной записи с HTTP-следом и без диагноза
следующая попытка блокируется.

```bash
poetry run python -m dualify.rq1_dev results/rq1-dev-2026-11-22 \
  --offline results/rq1-dev-reproduction
```

Offline-команда сверяет split, конфигурацию пулов, ревизии файлов scorer,
версию Z3 и HTTP-записи завершённых slots. Затем запускает gold scoring с
десятью dev-эталонами. Сравниваются итоговые метрики, oracle statuses и
reasons. Конкретные значения контрпримеров Z3 могут варьироваться.
[Реестр ограничений Dualify](../agent/KNOWN_DUALIFY_LIMITATIONS.md)

## Конфигурация Groq

- Модель `qwen/qwen3.8-27b`, instruct через `reasoning_effort=none`, chat
  completions с `response_format=json_object`. Baseline и repair используют
  `T=0`, initial treatment использует `T=0.7`. Groq применяет свой default
  `top_p=1`. [Groq](https://console.groq.com/docs/model/qwen/qwen3.8-27b) ·
  [Qwen](https://huggingface.co/Qwen/Qwen3.8-27B)
- Бюджет кампании составляет один запрос каталога и максимум 180 POST,
  включая transport retries и native repair. Максимум 1024 output tokens
  за запрос. Интервал между POST составляет минимум 18 секунд, timeout
  запроса 120 секунд. Для сетевой ошибки, 429 и 500/502/503/504 клиент
  допускает две физические отправки на логический вызов с backoff от 2 до
  60 секунд. [Лимиты Groq](https://console.groq.com/docs/rate-limits)
- Время попытки включает ожидание и backoff. Чистое inference time остаётся
  NA. Отчёт отдельно показывает логические вызовы и фактически наблюдавшиеся
  POST. Абсолютная квота зависит от настроек организации Groq.
