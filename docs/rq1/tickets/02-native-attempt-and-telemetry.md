# 02 — Одна штатная extraction attempt с температурой и учётом ошибок

**Статус:** выполнен 2026-11-20
**Blocked by:** [01 — Benchmark split и аудит](01-benchmark-split-and-audit.md).  
**Результат:** одна offline-проверяемая полная попытка extractor по каждому каналу с неизменным native validation/repair, правильной температурой и наблюдаемым конечным статусом.

## Problem
Оригинальные p01/p02 передают initial generation и repairs через интерфейс LLM client, который по умолчанию использует temperature 0. В sampling нужно менять температуру **только первого вызова**, сохранив prompts и recovery. При этом extractor может перехватить ошибку провайдера и вернуть degraded контракт, скрыв незавершённый инфраструктурный slot.

## Known facts
- `LLMClient.generate_json(prompt, temperature=0.0)` допускает явную температуру, но начальные вызовы и repairs в p01/p02 обычно используют значение по умолчанию.
- Оба extractors выполняют validation, возможные repair/safe-subset и degraded recovery; одна полная попытка включает несколько логических LLM calls.
- Оригинальный OpenAI-compatible client может повторять HTTP-запросы и переключать completion endpoint; количество HTTP attempts отличается от logical LLM calls.
- Утверждённый метод сохраняет repair ladder и T=0 для repair при фиксированной T>0 на первом treatment generation.
- Malformed JSON от модели не является автоматически временным инфраструктурным сбоем.

## Constraints
- Интегрируйся на **самой высокой безопасной границе client/orchestration**. Сохраняй signatures/prompts и формальную семантику extractors, пока конкретные доказательства не показывают необходимости минимального изменения.
- Одна **полная** invocation extractor = один candidate attempt, даже при weak/degraded postcondition.
- Baseline: initial и repair T=0; treatment: **initial** фиксированная T>0, все штатные repairs T=0. Сбрасывай состояние adapter между попытками.
- По фактам различай transport/rate-limit/5xx, permanent config/auth/model, ошибку формата модели и ambiguous ответы. Сохраняй исходную причину, не классифицируя исключительно по HTTP status.
- Retries разрешены только для временной инфраструктуры с конечным и записанным лимитом; invalid JSON/formulas не дают бесплатного resampling. Ошибку инфраструктуры, скрытую degraded fallback, отмечай как incomplete slot.
- API credentials не попадают в logs. Все тесты используют fake clients. Не изменяй Z3/p03–p05.

## Hypotheses
- **Инженерная гипотеза:** per-attempt client adapter способен различать initial и repair calls, не меняя штатный repair ladder, и сохранять достаточные сведения об ошибках для честного учёта slots.
- Если исходный API не раскрывает нужный статус, документируй границу наблюдаемости и предлагай минимальное проверяемое изменение, не выдумывая telemetry.

## Expected outcome
- По одному полному примеру spec и code на fake responses с проверкой температур, сохранением штатного результата и stage trace.
- Нормализованная запись attempt: slot ID, model/settings, final extraction, temperature sequence, logical-call count, elapsed time и категория ошибки/её доказательства.
- Тесты успешного initial extraction, штатного repair, degraded результата, ограниченных transient retries, non-retriable config failure и output-format ошибки как результата модели/extraction.

## Acceptance criteria
- [x] Fake-client integration подтверждает **T>0 только для treatment initial** и T=0 для всех следующих native repairs в обоих каналах.
- [x] T=0 baseline использует ровно оригинальный полный extractor; при одинаковых fake responses содержание/trace сохраняются.
- [x] Invalid/degraded extraction вследствие ответа модели считается завершённым кандидатом, а не поводом повторять генерацию.
- [x] Исчерпанная инфраструктурная ошибка, перехваченная внутри extractor, помечается incomplete, не incorrect candidate.
- [x] Auth, unsupported model/endpoint и permanent config останавливают с объяснением; transient retries ограничены и логируются.
- [x] Есть тесты на HTTP 4xx, вызванные output-validation: они не считаются обычной временной недоступностью.
- [x] Существующие regression tests проходят; для проверки тикета Groq не нужен.

## Реализация

- `dualify.rq1_attempt.run_extraction_attempt` создаёт новый adapter на каждый slot и вызывает
  неизменённый `extract_spec_logic` либо `extract_code_logic`.
- Attempt record хранит slot/model/settings, native extraction, стадии и ответы logical calls,
  видимые передачи в inner client, ошибки и полное wall-clock время вызова extractor.
- Физические HTTP retries внутри provider client по-прежнему не наблюдаются и не выводятся из
  `dispatch_count`; это ограничение сохранено как `RQ1-003`.

## Stopping criteria
**STOP, когда:** оба канала проходят тесты полной attempt, маршрутизации temperature и классификации ошибок; существующий test suite зелёный; пример attempt record воспроизводим. Если adapter не может сохранить поведение оригинального extractor, укажи `BLOCKED`, минимальное воспроизведение и необходимое точечное изменение. Не создавай четырёхкандидатные пулы, не запускай live-модель и не улучшай несвязанные модули.

## Out of scope
Sampling n=4, финальный анализ pass@k, live dev/test и переписывание native repair.
