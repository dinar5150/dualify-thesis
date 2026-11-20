# Точка входа для AI-агента

Этот репозиторий содержит исследование **RQ1 бакалаврского диплома** на основе оригинального Dualify. Подробные инструкции для агентов находятся в [docs/agent/](docs/agent/README.md).

1. **Прочитай [docs/agent/AGENT_GUIDE.md](docs/agent/AGENT_GUIDE.md)** перед выполнением тикета RQ1. Там описаны порядок работы, условия допуска к этапам и критерии остановки.
2. **Прочитай [docs/agent/KNOWN_DUALIFY_LIMITATIONS.md](docs/agent/KNOWN_DUALIFY_LIMITATIONS.md)** перед исследованием оригинального алгоритма Dualify или поведения Z3. Сохраняй исходный Z3 oracle, timeout solver, семантику поддерживаемого фрагмента и штатные extraction/repair. Известные недостатки документируй, а не исправляй в рамках RQ1.
3. **Прочитай [docs/rq1/SPEC.md](docs/rq1/SPEC.md)** и [docs/rq1/PROTOCOL.md](docs/rq1/PROTOCOL.md), затем выбери **один незаблокированный тикет** из [docs/rq1/tickets/README.md](docs/rq1/tickets/README.md). Остановись сразу после выполнения его явных критериев завершения.

**Текущий допуск:** только обслуживание документации. Это изменение не разрешает реализацию на Python, эксперименты с Groq или запуск held-out test.
