# RQ1. Технический разбор Dualify и Z3

Материал для научного руководителя · 24 ноября 2026 г.

В dev-пилоте по десяти задачам Dualify сохранил 100 финальных контрактов. Сравнение с эталоном подтвердило 13 совпадений и 67 расхождений. В десяти случаях Z3 оставил вопрос открытым, а ещё десять результатов остались без классификации из-за ошибки разбора одного эталона. Ниже прослежены конкретные ответы от запроса к модели до результата сравнения. Слово **наблюдение** относится к сохранённой записи, **причина** — к механизму, подтверждённому кодом или запуском, **гипотеза** — к объяснению с недостающим доказательством, **предложение** — к ещё не утверждённому изменению. [Freeze](../artifacts/dev-2026-11-22-vpn-freeze.json) · [Архив](../artifacts/dev-2026-11-22-vpn.tar.gz)

## 1. Источники и версии

Первичный набор для анализа — `dev-2026-11-22-vpn.tar.gz`, SHA-256 `1ba56e39431a62dfde4b3b5057ed6ebba5c47b65af6aadc1c19d43f2bb88f74c`. В архиве `preflight.json` и `resume-preflight.json` задают конфигурацию, `http/<ID>.json` хранит отправленный prompt и тело ответа, `pools/<задача>/<слот>/result.json` хранит логические вызовы и итог, а `offline-diagnostics.json:scores` — исходы сравнения. Приведённые ниже ID относятся к этой версии архива. Публичная копия маскирует идентификатор организации в текстах ошибок. Полнота внутренних промежуточных состояний зависит от ветки extractor. [Архив](../artifacts/dev-2026-11-22-vpn.tar.gz) · [Протокол записи](../TICKET_05_DEV.md)

Исходный Dualify — `7ffd1ae37822096d5b7b573785ee46e877903185`. Этапы dev использовали `c8d559bef7c47a87d44e6bca0245cbdf30b6665e` и `b11301cb0d77fcbd4fa95b7ac24c4e203bcc5e74`. Анализ выполнен на `96f4896da31433dad46d2876e4efef181e579a03`, Python 3.14.4, `z3-solver` 4.16.0.0. Файлы p01, p02, p03, нормализатора и расчёта отношения формул совпадают с upstream на указанных Git-объектах. В gold scoring добавлены проверка уникальности benchmark ID и возврат подробного SMT-результата. Для атрибуции исходного метода использованы доступные код и README Git-ревизии. Текст исходной статьи из конференционного submodule недоступен. [README исходной ревизии](https://raw.githubusercontent.com/timur-harin/dualify/7ffd1ae37822096d5b7b573785ee46e877903185/README.md) · [Scorer](../../../src/dualify/gold_scoring.py) · [Freeze](../artifacts/dev-2026-11-22-vpn-freeze.json)

## 2. От Python до pass@k

Для RQ1 из 40 исходных пар Python и YAML заранее выбрали 10 dev и 30 held-out задач с seed `20261120`. На задачу и канал записали одну контрольную и четыре treatment-попытки. Модель `qwen/qwen3.8-27b` получала только описание или код, сигнатуру и доступный контекст. Baseline и repair были настроены на T=0, начальный treatment на T=0,7. Endpoint Groq — `/openai/v1/chat/completions` в режиме JSON object с `reasoning_effort=none`, default `top_p=1`, максимумом 1024 выходных токенов и HTTP timeout 120 с. Одна попытка включает до трёх логических запросов, а каждый запрос может повторяться на уровне HTTP при временном сбое. [Дизайн RQ1](../RQ1.md) · [Настройки dev](../TICKET_05_DEV.md#конфигурация-groq)

| Этап и код | Вход, выход и проверка | Где может исчезнуть информация |
| --- | --- | --- |
| Вход и prompt. [discovery](../../../src/dualify/discovery.py#L58-L85), [p01](../../../src/dualify/phases/p01_spec_to_logic.py#L284-L362), [p02](../../../src/dualify/phases/p02_code_to_logic.py#L285-L363) | `discover_python_cases` формирует сигнатуру, описание из комментария или docstring и сегмент функции. `extract_spec_logic` и `extract_code_logic` вставляют свой канал и правила формул в prompt. `run_extraction_attempt` передаёт данные `BenchmarkCase`, включая типы. | Отдельно переданное тело может не содержать инварианта класса или определения helper. Текстовое описание может опускать часть поведения. |
| HTTP-ответ и разбор JSON. [OpenAICompatibleClient](../../../src/dualify/ollama_client.py#L173-L249), [`_extract_json_object`](../../../src/dualify/ollama_client.py#L19-L33), [адаптер](../../../src/dualify/rq1_attempt.py#L66-L139) | Из тела HTTP 200 берётся `choices[0].message.content`, из него клиент разбирает объект. Записываются температура, стадия и доступный ответ. Заголовки и повторы относятся к отправкам, а не к дополнительным кандидатам. | Ошибка формата у провайдера может завершить вызов без принятого JSON, как HTTP 400 `json_validate_failed`. Extractor передаёт дальше пустой payload при исключении. Адаптер отличает ошибки модели от неустранённых инфраструктурных ошибок. |
| Coercion. [`_extract_signature_args` и `_coerce_payload`](../../../src/dualify/phases/p02_code_to_logic.py#L83-L112) | В `args` подставляется результат разбора сигнатуры. `domain_constraints` оставляет только строки, отсутствие постусловия даёт `ret == ret`, прочие поля получают типизированные default. | Ошибки raw-полей могут исчезнуть до проверки. Разделение сигнатуры по запятой внутри вложенной аннотации вводит лишний элемент `args` в `swap`. |
| Normalization. [`normalize_formula`](../../../src/dualify/formula_parser.py#L180-L359), [`ensure_ret_reference`](../../../src/dualify/formula_parser.py#L431-L451), [обработка payload](../../../src/dualify/phases/p02_code_to_logic.py#L140-L152) | Формулы разбираются как Python AST и переписываются. Поддерживаемый срез становится `Extract`, сравнение с кортежем — равенствами полей, `ret == None` — `Length(ret) == 0`. Псевдонимы результата становятся `ret`. Для выражения без `ret` возможна обёртка `ret == (...)`. | Преобразования предполагают определённую форму и тип. Результат нормализации может оказаться за пределами разрешённых вызовов (пример `Char`). Строку, которая не парсится как AST, нормализатор обычно оставляет для диагностики. |
| Validation. [p01](../../../src/dualify/phases/p01_spec_to_logic.py#L115-L192), [p02](../../../src/dualify/phases/p02_code_to_logic.py#L115-L192), [`validate_formula`](../../../src/dualify/formula_parser.py#L524) | Проверяются форма AST, имена, список вызовов, инфиксный `And/Or`, ссылки на результат и эвристики качества постусловия. Имена связываемых переменных квантора разрешены. | Допустимая для Z3 конструкция может быть запрещена списком Dualify. Соответствие сигнатуре проверяется после подстановки `args`. Прохождение проверки не устанавливает, что формула описывает поведение Python. |
| Предварительная типизация. [`_typecheck_errors`](../../../src/dualify/phases/p02_code_to_logic.py#L19-L30), [`extraction_parseable` и `is_parseable`](../../../src/dualify/phases/p03_smt_checking.py#L869-L931) | После синтаксической проверки формулы канонизируются, проходят грубые текстовые проверки, переводятся в выражения Z3 с типами сигнатуры. При отсутствии `arg_types` этот шаг пропускается. | Ошибки перевода, сортов и эвристик сворачиваются в одно сообщение. Пустой benchmark ID в этой ветке может повредить текст формулы до типизации. Проверка вычислимости не решает эквивалентность и сама по себе не гарантирует булев тип результата. |
| Обычный repair. [p01](../../../src/dualify/phases/p01_spec_to_logic.py#L194-L234), [p02](../../../src/dualify/phases/p02_code_to_logic.py#L194-L235) | Модель получает сигнатуру, список ошибок и текущий нормализованный JSON. Новый JSON проходит те же проверки. При успехе он целиком заменяет прежний payload. | Ограничения могут измениться при полной замене. При успехе в архивном нативном трейсе может остаться только `final`. Источники промежуточных деталей в этом случае — repair prompt и raw HTTP. |
| Safe-subset repair. [p01](../../../src/dualify/phases/p01_spec_to_logic.py#L236-L282), [p02](../../../src/dualify/phases/p02_code_to_logic.py#L237-L282) | При втором отказе модель снова получает сигнатуру, исходный текст или код и более узкие правила. Принимается допустимая частичная формула. Такой итог маркируется `recovered_safe_subset`. | Упрощённый запрос не переносит предыдущий список ошибок и может терять условия. Фраза о безопасном подмножестве в prompt задаёт просьбу к модели. Формальная проверка эквивалентности с первым ответом здесь отсутствует. |
| Salvage и заглушка. [p02](../../../src/dualify/phases/p02_code_to_logic.py#L425-L475), [`salvage_valid_conjuncts`](../../../src/dualify/formula_parser.py#L454-L508) | При провале safe repair по очереди разбираются постусловия safe, обычного repair и initial. Принимается первая восстановимая конъюнкция из отдельно проверенных верхнеуровневых частей. Предусловия берутся из safe payload и фильтруются через проверку выражения. При отсутствии восстанавливаемой части выход — `[]` и `ret == ret`. | Конъюнкты и весь исходный домен могут пропасть. Даже валидное условие из первого payload не переносится автоматически. Новая комбинация pre/post на этой ветке не проходит повторную полную проверку тела контракта. |
| `ExtractionResult` и сохранение. [типы](../../../src/dualify/types.py#L19-L39), [p01](../../../src/dualify/phases/p01_spec_to_logic.py#L475-L493), [пулы](../../../src/dualify/rq1_pool.py#L216-L319) | Итог содержит ID, `args`, return type, формулы, `confidence`, `notes`, флаги degraded и `extraction_trace`. Исследовательская запись добавляет слот, температуры, вызовы, ошибки и время. | `confidence` и `degraded` сообщают о пути генерации. Они не заменяют проверку качества. Offline scorer открывает только сохранённый финал. |
| Сопоставление с gold. [`load_gold_benchmark`](../../../src/dualify/gold_scoring.py#L83-L148), [score](../../../src/dualify/gold_scoring.py#L196-L253), [RQ1-агрегатор](../../../src/dualify/rq1_report.py#L179-L234) | По полному benchmark ID выбирается эталон. Сначала используются `reference_normalized`, при его отсутствии `reference_pre/post`. CaseSpec получает типы gold. Scorer записывает точное совпадение строк после нормализации, отношение силы условий и SMT-verdict. | Эталон задаёт ограниченный профиль наблюдаемого поведения. Пустое или спорное gold-предусловие меняет задачу, которую реально решает oracle. |
| Z3 и классификация. [`check_equivalence`](../../../src/dualify/phases/p03_smt_checking.py#L503-L865), [`_candidate`](../../../src/dualify/rq1_report.py#L40-L92) | Проверяются расхождения предусловий и, при их согласии, постусловий на общем домене. RQ1 классифицирует финал по причине и диагностике. | Перевод может завершиться до Z3 solver. Z3 может ответить `unknown`. Невозможность проверить эталон блокирует утверждённую полную агрегацию. |
| Pass@k. [`_task_channel` и `_bootstrap`](../../../src/dualify/rq1_report.py#L95-L176) | Для четырёх treatment-финалов считаются подтверждённые успехи `c` и неопределённые исходы `u`. Оценки для каждой задачи усредняются по каналу. Baseline хранится отдельно. | Метрика использует наличие успеха среди *k* попыток, у которых одинаковая постановка. Она не оценивает выбор конкретного контракта и зависит от покрытия и семантики gold. |

## 3. Как oracle принимает решение

Обозначим предусловия gold и кандидата как `G` и `C`, их постусловия как `Pg` и `Pc`. Пустой список предусловий становится `True`. Checker строит область переменных из типов gold. Типы некоторых дополнительных имён выводятся по тексту формул. В `_safe_eval` выражения переводятся в Z3Py, индексы кванторов получают тип Int, а часть строковых операций использует обёртки Dualify. Задача solver — проверить выполнимость полученных формул. [Контекст проверки](../../../src/dualify/phases/p03_smt_checking.py#L465-L554) · [Перевод и кванторы](../../../src/dualify/phases/p03_smt_checking.py#L167-L283)

1. `Xor(G, C)` ищет вход, который разрешает ровно один контракт. `sat` даёт свидетель и завершает основной verdict на предусловиях. Две проверки импликации определяют направление. `case_pre_spec` и `case_pre_code` используют внутренние роли gold и кандидата. Они имеют одинаковый смысл в обоих каналах генерации. Это метки ветвей: `case_pre_code` выбирается, если направление из gold в кандидата не доказано при уже найденном расхождении. При доказанном расхождении в обе стороны метка всё равно будет `case_pre_code`. Для вывода о силе надо смотреть обе импликации. [Код предусловий](../../../src/dualify/phases/p03_smt_checking.py#L609-L738)
2. Если предусловия согласованы, solver получает общий домен `G ∧ C` и требование расхождения `Xor(Pg, Pc)` на нём. `unsat` при пройденной эвристике словаря постусловий даёт `equivalent_no_mismatch`. При `sat` запускаются две дополнительные проверки направления. Публичный контрпример постусловия содержит входы. В `diagnostics.debug.witness_model` сохраняется и `ret`, на котором получено расхождение. Отдельная функция `contract_relation` вычисляет отношения силы условий, в том числе на общем домене при разных предусловиях. [Код постусловий](../../../src/dualify/phases/p03_smt_checking.py#L740-L865) · [Отношения силы](../../../src/dualify/relation.py#L70-L123)
3. `unknown` означает, что конкретная проверка solver не завершилась решением `sat/unsat`. Dualify сохраняет шаг (`solver_unknown_pre`, `solver_unknown_post` или `solver_unknown_post_direction`) и лимит 5000 мс на каждый `check()`. В архиве отсутствует `reason_unknown()`, поэтому точный механизм остановки конкретного вызова неизвестен. Если XOR уже был `sat`, а направление осталось неопределённым, исходный checker может вернуть `solver_unknown` с контрпримером. RQ1 консервативно относит этот случай к `inconclusive`. `vacuous_equivalence` тоже попадает в `inconclusive`; в dev таких финалов не было. [Лимит и статусы](../../../src/dualify/phases/p03_smt_checking.py#L453-L462) · [Правила RQ1](../../../src/dualify/rq1_report.py#L54-L77) · [Z3Py Solver](https://z3prover.github.io/api/html/classz3py_1_1_solver.html)
4. Когда перевод в формулы завершается исключением, checker возвращает `formula_parse_error`. RQ1 присваивает `invalid`, только если эталон отдельно разбирается, а финальный кандидат отдельно — нет. Когда отказ нельзя однозначно отнести к кандидату, аналитика блокируется с `unclassified`. В `parse_input` исключение возникает при разборе gold, ещё до запуска solver. Для текущего fragment признак `in_fragment: true` в YAML указывает предполагаемую пригодность эталона. Практическую проверяемость показывает self-check. [Разбор и классификация](../../../src/dualify/rq1_report.py#L40-L77)

Сорт `List[str]` в Dualify — последовательность Z3-строк. Строка и отдельный символ имеют разные типы. `Tuple[int, int, str]` исходный переводчик сводит к `Seq(Int)`, теряя тип третьего элемента и фиксированную арность. `Optional[Tuple[int,int]]` сводится к базовому типу, а отсутствие результата моделируется пустой последовательностью. Эти решения приняты в Dualify. В Z3 есть алгебраические типы с полями разных сортов. Операции из Z3Py, такие как `IndexOf`, могут быть доступны переводчику, но отсутствовать в разрешённом языке extractor. Сравнение оценивает формулы в этой кодировке, включая представление float через Real, и может не воспроизводить машинное округление, исключения и границы определённости индексирования Python. [Перевод типов](../../../src/dualify/phases/p03_smt_checking.py#L28-L88) · [Справочник строк Z3](https://microsoft.github.io/z3guide/docs/theories/Strings/) · [Справочник типов данных Z3](https://microsoft.github.io/z3guide/docs/theories/Datatypes/)

## 4. Таксономия отказов

| Механизм и наблюдение | Подтверждённая причина или гипотеза | Что меняет и как проверить исправление |
| --- | --- | --- |
| Синтаксис raw JSON-контракта. `swap/0009` с инфиксным `And`, `csv/0058` со стрелкой, `solve/0241` с лишней скобкой | Модель выдала выражения, которые не проходят правила AST. У `swap` последующий вызов `And(...)` принят. | Меняет число repair и вероятность fallback. Проверить эквивалентную запись одного и того же предиката в сохранённом ответе до теста с генерацией. [Трейсы CSV](#trace-csv-first-column) · [swap](#trace-swap) |
| Неизвестный оператор или идентификатор. `average/0039` с `sum`, `0040` с `true`, CSV со срезом, `.index` или `IndexOf` | Доступные в Python приёмы не входят в ограниченный DSL. Синтаксически недопустимый фрагмент может скрыть следующий отказ allowlist. | Oracle получает результат восстановления, иногда заглушку. Проверять арифметику, типы и поведенческую корректность предлагаемой замены отдельно. [average](#trace-average) · [CSV](#trace-csv-first-column) |
| Связка нормализации и типов. `csv/0059`, `extract_expression`, `determine_column` | Символьное сравнение нормализуется в `Char`, затем этот вызов отвергает extractor. При обходе allowlist на `0059` срабатывает второй отказ предварительной проверки. Пустой ID может заменить вызовы свободными именами. | Проверять конкретный преобразованный AST со штатным и изолированным валидатором. Изменение затронет траектории repair и требует отдельного сравнения генерации. [Изолированные проверки](#exp-char) |
| Потеря условий в repair или fallback. `average`, `solve`, `parse_input`, ослабление постусловия в CSV | Обычный repair заменяет контракт целиком. Salvage выбирает отдельные конъюнкты, fallback очищает предусловия. | В 52 из 67 доказанных расхождений первой обнаружена проблема предусловий. Это результат сравнения финалов, без оценки промежуточных контрактов. Проверить точное ранее валидное требование и изменение вердикта на контрольном входе. [Архив](../artifacts/dev-2026-11-22-vpn.tar.gz) · [Распределение validation](../figures/dev-validation-errors.png) |
| Тип результата и разбор gold. `parse_input` | Выбрана однородная последовательность элементов первого типа. Сбой self-check локализует потерю строкового поля независимо от генерации. | Один эталон исключён из условного знаменателя. Проверить self-check и контроль неверной высоты, затем расхождения исходного и альтернативного oracle на тех же финалах. [Эксперимент](#exp-tuple) |
| Неопределённость solver. `csv_first_column` | Статусы указывают незавершённые проверки с кванторами и последовательностями. Причина каждого `unknown` и причина расхождения между историческими проходами остаются гипотезами. | Сохранять статусы отдельных проверок, `reason_unknown()` в согласованной диагностике и агрегаты из одного прохода. Локально проверить конечный пример на заданной строке, сохраняя исходный verdict отдельно. [Повторное сравнение](#exp-scores) · [RQ1-013](../../agent/KNOWN_BUGS.md) |
| Семантический профиль gold и видимый вход. `duration`, `next_departure`, `solve`, `parse_input`, `extract_expression` | Код и эталон расходятся на конкретных входах. Отсутствие helper в `determine_column` подтверждается prompt, вклад этого отсутствия в выбор модели требует эксперимента. | Разложить результат на домен, постусловие и выбранную цель. Для добавленного контекста сравнить прежний и дополненный prompt при одном oracle и бюджете. [Тесты Python](#exp-python) · [Обзор контекста задач](../tickets/06-dev-diagnostics-and-supervisor-review.md#разбор-проблемных-dev-задач) |
| HTTP и режим запуска. Два 400 и 16 ответов 429 в журнале, отдельный 403 при попытке возобновления | 400 имеют `json_validate_failed`. 429 отражают квоту или лимит провайдера. Точная причина отдельного 403 по его телу неизвестна. | Меняет задержку и полноту слотов. Для следующей кампании проверять счётчики POST, логических вызовов, слотов и пауз при возобновлении. [История dev](../TICKET_05_DEV.md) |

## 5. Трейсы по задачам

Семь задач показывают разные исходы одной цепочки. Для контраста включён успешный repair. Ещё три задачи описаны в первичном отчёте. [zipped_pairs](../tickets/06-dev-diagnostics-and-supervisor-review.md#case-zipped-pairs) · [extract_expression](../tickets/06-dev-diagnostics-and-supervisor-review.md#case-extract-expression) · [determine_column](../tickets/06-dev-diagnostics-and-supervisor-review.md#case-determine-column)

| Трейс | Что устанавливает наблюдение |
| --- | --- |
| [`average`](#trace-average) | Первый ответ выражает среднее через запрещённый вызов. Fallback удаляет и вычисление, и корректное ограничение входа. |
| [`csv_first_column`](#trace-csv-first-column) | Нормализация добавляет запрещённый `Char`. Salvage сохраняет только длину результата. Проверка постусловия остаётся неопределённой. |
| [`parse_input`](#trace-parse-input) | Gold сам по себе не разбирается. В первом ответе есть независимая проблема с вызовом `Concat`. |
| [`next_departure`](#trace-next-departure) | Два из четырёх кодовых финалов совпали с gold. Единственный подтверждённый вклад в прирост обеспечил этот пул. |
| [`duration`](#trace-duration) | По описанию потерян `+1`, по коду потеряно gold-предусловие. |
| [`solve`](#trace-solve) | Oracle отвергает заглушку на предусловии. Отдельный запуск Python выявляет расхождение gold и кода на дубликатах. |
| [`swap`](#trace-swap) | Repair исправляет форму выражения и получает эквивалентный финал при дефекте метаданных `args`. |

У каждого HTTP 200 показаны разобранные исходные поля JSON с декодированным экранированием. `pre` обозначает `domain_constraints`, `post` — `postcondition`. Строка под ними показывает сохранённый переход после обработки и решение валидатора. Поля `notes` и `confidence`, полные initial/repair prompts и ответы доступны в HTTP по указанному ID. Формулы после обработки взяты из нативного трейса либо из JSON, процитированного в repair prompt. При отсутствии промежуточной записи зафиксирован только подтверждённый итог. Операции между `pre/post` и стрелкой сводятся к штатной обработке из раздела 2. Команда чтения полного HTTP входит в [приложение](#reproduce).

<a id="trace-average"></a>

### `average`. Среднее и ограничение языка формул

Код вычисляет `sum(numbers) / len(numbers)`. Gold задаёт непустой список и границы результата. Формула первого ответа передаёт вычисление на уровне математического выражения. Представление чисел как SMT Real уже отличается от машинного float Python.
[Python-вход](../../../benchmark/lifted_auto_eval/crosshair_examples_deal_correct_code_average.py_average.py) · [Gold YAML](../../../benchmark/lifted/crosshair_examples_deal_correct_code_average.py_average.yaml)

Эталон, поля, которые читает scorer.

```text
pre = ["Length(numbers) > 0"]
post = And(Exists([k], And(0 <= k, k < Length(numbers), numbers[k] <= ret)), Exists([k], And(0 <= k, k < Length(numbers), numbers[k] >= ret)))
```

**Слот** `crosshair_examples::deal::correct_code::average.py::average:code:treatment:1`. HTTP: `0038.json` (429), `0039.json` (200), `0040.json` (200), `0041.json` (429), `0042.json` (200).

Фрагмент входа модели из HTTP-записи с сигнатурой и предметным контекстом.

```text
Signature:
average(numbers: List[float]) -> float

Function source:
def average(numbers: List[float]) -> float:
    return sum(numbers) / len(numbers)

Additional context:
```

**initial, HTTP 0039, T=0.7.**

```text
args = ["numbers"]
return_type = float
pre = ["Length(numbers) > 0"]
post = ret == (sum(numbers) / Length(numbers))
После обработки (из extraction_trace):
post → ret == sum(numbers) / Length(numbers)
validation = ["postcondition unsupported function calls: sum"]
```

**repair, HTTP 0040, T=0.0.**
 В промпте `Errors to fix` = `["postcondition unsupported function calls: sum"]`, затем нормализованный первый JSON в `Current invalid JSON`.

```text
args = ["numbers"]
return_type = float
pre = ["Length(numbers) > 0"]
post = ret == (ForAll([i], Implies(And(0 <= i, i < Length(numbers)), true))) / Length(numbers)
После обработки (из extraction_trace):
post → ret == ForAll([i], Implies(And(0 <= i, i < Length(numbers)), true)) / Length(numbers)
validation = ["postcondition unknown identifier `true`", "postcondition must not assign quantifier directly to ret"]
```

**safe_repair, HTTP 0042, T=0.0.**
 В промпте — исходная сигнатура и контекст, правила упрощённого фрагмента и просьба сохранить частичную формулу; список ошибок предыдущей проверки отдельно не передан.

```text
args = ["numbers"]
return_type = float
pre = ["Length(numbers) > 0"]
post = Exists([s], And(s == ret * Length(numbers), ForAll([i], Implies(And(0 <= i, i < Length(numbers)), s == s + numbers[i] - numbers[i]))))
После обработки (из extraction_trace):
pre и post совпадают с raw
validation = ["postcondition/constraints fail Z3 type check"]
```

**Итог и сравнение.**

```text
pre = []
post = ret == ret
degraded = True sanitize_after_validation_failure
oracle = non_equivalent · case_pre_spec
solver_status = {"pre_mismatch_check": "sat", "pre_spec_implies_pre_code": "unsat", "pre_code_implies_pre_spec": "sat"}
well_formedness = ok
counterexample = {"numbers": "Empty(Seq(Real))"}
```

[Архив с HTTP, prompts и результатом слота](../artifacts/dev-2026-11-22-vpn.tar.gz)

Ответ `0039` отклонён за `sum`. В `0040` модель заменила сумму булевым квантором. В `0042` она связала сумму с выражением `s == s + numbers[i] - numbers[i]`, которое ничего не сообщает о сумме. Архивный type-check отказ не локализует конкретную подформулу. В заглушке исчезло точное предусловие `Length(numbers) > 0`, присутствовавшее до самого fallback. 429 в HTTP 0038 и 0041 относятся к отправке запросов. Контрпример пустого списка доказывает расхождение доменов финала и gold. Отдельный контроль `[1., 3.]` показывает, что более точная формула могла бы сузить диапазон gold. Следующая проверка — сохранить валидный домен в изолированном fallback и отдельно проверить, выражает ли новый оператор суммы нужную семантику на коротком списке. [Поведенческая проверка](#exp-python)

<a id="trace-csv-first-column"></a>

### `csv_first_column`. Первый столбец CSV, Char и неопределённый результат Z3

Следует вернуть префикс каждой строки до первой запятой. Описание явно требует запятую в каждой строке. Gold сравнивает длины списков, префиксы и положение первой запятой.
[Python-вход](../../../benchmark/lifted_auto_eval/crosshair_examples_icontract_correct_code_showcase.py_csv_first_column.py) · [Gold YAML](../../../benchmark/lifted/crosshair_examples_icontract_correct_code_showcase.py_csv_first_column.yaml)

Эталон, поля, которые читает scorer.

```text
pre = ["ForAll([_k0], Implies(And(0 <= _k0, _k0 < Length(lines)), Contains(lines[_k0], ',')))"]
post = And(Length(ret) == Length(lines), ForAll([_k0], Implies(And(0 <= _k0, _k0 < Length(lines)), And(PrefixOf(ret[_k0], lines[_k0]), Not(Contains(ret[_k0], ',')), PrefixOf(Concat(ret[_k0], ','), lines[_k0])))))
```

**Слот** `crosshair_examples::icontract::correct_code::showcase.py::csv_first_column:spec:treatment:1`. HTTP: `0058.json` (200), `0059.json` (200), `0060.json` (200).

Фрагмент входа модели из HTTP-записи с сигнатурой и предметным контекстом.

```text
Signature:
csv_first_column(lines: List[str]) -> List[str]

Informal specification:
Behavior of csv_first_column: for each line in `lines`, return the substring of the line up to (but not including) the first comma. Requires every line to contain at least one comma.

Additional context:
```

**initial, HTTP 0058, T=0.7.**

```text
args = ["lines"]
return_type = List[str]
pre = ["ForAll([i], i < Length(lines) -> Contains(lines[i], ','))"]
post = And(Length(ret) == Length(lines), ForAll([i], i < Length(lines) -> ret[i] == lines[i][:lines[i].find(',')]))
После обработки (из extraction_trace):
pre и post совпадают с raw
validation = ["postcondition invalid expression syntax: invalid syntax (<unknown>, line 1)", "domain constraint invalid expression syntax: invalid syntax (<unknown>, line 1)"]
```

**repair, HTTP 0059, T=0.0.**
 В промпте `Errors to fix` = `["postcondition invalid expression syntax: invalid syntax (<unknown>, line 1)", "domain constraint invalid expression syntax: invalid syntax (<unknown>, line 1)"]`, затем нормализованный первый JSON в `Current invalid JSON`.

```text
args = ["lines"]
return_type = List[str]
pre = ["ForAll([i], Implies(And(0 <= i, i < Length(lines)), Contains(lines[i], ',')))"]
post = And(Length(ret) == Length(lines), ForAll([i], Implies(And(0 <= i, i < Length(lines)), Exists([j], And(0 <= j, j < Length(lines[i]), lines[i][j] == ',', ForAll([k], Implies(And(0 <= k, k < j), ret[i][k] == lines[i][k])), Length(ret[i]) == j)))))
После обработки (из extraction_trace):
post → And(Length(ret) == Length(lines), ForAll([i], Implies(And(0 <= i, i < Length(lines)), Exists([j], And(0 <= j, j < Length(lines[i]), lines[i][j] == Char(','), ForAll([k], Implies(And(0 <= k, k < j), ret[i][k] == lines[i][k])), Length(ret[i]) == j)))))
validation = ["postcondition unsupported function calls: Char"]
```

**safe_repair, HTTP 0060, T=0.0.**
 В промпте — исходная сигнатура и контекст, правила упрощённого фрагмента и просьба сохранить частичную формулу; список ошибок предыдущей проверки отдельно не передан.

```text
args = ["lines"]
return_type = List[str]
pre = ["ForAll([i], Implies(And(0 <= i, i < Length(lines)), Contains(lines[i], ',')))"]
post = And(Length(ret) == Length(lines), ForAll([i], Implies(And(0 <= i, i < Length(lines)), ret[i] == Extract(lines[i], 0, IndexOf(lines[i], ','))))))
После обработки (из extraction_trace):
pre и post совпадают с raw
validation = ["postcondition invalid expression syntax: unmatched ')' (<unknown>, line 1)"]
```

**Итог и сравнение.**

```text
pre = ["ForAll([i], Implies(And(0 <= i, i < Length(lines)), Contains(lines[i], ',')))"]
post = Length(ret) == Length(lines)
degraded = True salvaged_partial_postcondition
oracle = inconclusive · solver_unknown
solver_status = {"pre_mismatch_check": "unsat", "pre_spec_implies_pre_code": "unsat", "pre_code_implies_pre_spec": "unsat", "post_mismatch_check": "unknown"}
well_formedness = solver_unknown_post
counterexample = null
```

[Архив с HTTP, prompts и результатом слота](../artifacts/dev-2026-11-22-vpn.tar.gz)

В `0058` стрелку и срез написал сам генератор. В `0059` генератор заменил срез квантором, но его формула указывает некоторую запятую: условия об отсутствии запятых до позиции `j` нет. Вызов `Char(',')` в тексте ниже появляется на стороне нормализатора. `0060` содержит лишнюю закрывающую скобку. Salvage сохранил равенство длин из разобранного repair и предусловие из safe-ответа. Точный отброшенный конъюнкт начинается с `ForAll([i], Implies(... Exists([j], ...)))` и приведён целиком на этапе нормализованного repair. Список `["x"]` на входе `["a,b"]` иллюстрирует слабость итогового условия, но oracle этого свидетеля не выдавал. Зонд меняет правило `Char` и предварительную канонизацию по одному условию; проверка семантики первой запятой на строке `a,b,c` остаётся отдельным шагом. [Проверка Char](#exp-char)

<a id="trace-parse-input"></a>

### `parse_input`. Разбор карты и смешанный тип результата

Функция берёт ширину из первой строки, считает строки и склеивает их. Gold фиксирует ширину, высоту и длину результирующей строки. Символы строки он оставляет свободными.
[Python-вход](../../../benchmark/lifted_auto_eval/python_by_contract_correct_aoc2020_day_3_toboggan_trajectory.py_parse_input.py) · [Gold YAML](../../../benchmark/lifted/python_by_contract_correct_aoc2020_day_3_toboggan_trajectory.py_parse_input.yaml)

Эталон, поля, которые читает scorer.

```text
pre = ["Length(lines) > 0"]
post = And(ret[0] == Length(lines[0]), ret[1] == Length(lines), Length(ret[2]) == Length(lines[0]) * Length(lines))
```

**Слот** `python_by_contract::correct::aoc2020::day_3_toboggan_trajectory.py::parse_input:code:treatment:1`. HTTP: `0183.json` (200), `0184.json` (200), `0185.json` (200).

Фрагмент входа модели из HTTP-записи с сигнатурой и предметным контекстом.

```text
Signature:
parse_input(lines: List[str]) -> Tuple[int, int, str]

Function source:
def parse_input(lines: List[str]) -> Tuple[int, int, str]:
    """Parse the input map given as ``lines``."""
    width: int = len(lines[0])
    height: int = len(lines)
    return width, height, "".join(lines)

Additional context:
```

**initial, HTTP 0183, T=0.7.**

```text
args = ["lines"]
return_type = Tuple[int, int, str]
pre = ["Length(lines) >= 1"]
post = And(ret[0] == Length(lines[0]), ret[1] == Length(lines), ret[2] == Concat(lines))
После обработки (из extraction_trace):
pre и post совпадают с raw
validation = ["postcondition/constraints fail Z3 type check"]
```

**repair, HTTP 0184, T=0.0.**
 В промпте `Errors to fix` = `["postcondition/constraints fail Z3 type check"]`, затем нормализованный первый JSON в `Current invalid JSON`.

```text
args = ["lines"]
return_type = Tuple[int, int, str]
pre = ["Length(lines) >= 1"]
post = And(ret[0] == Length(lines[0]), ret[1] == Length(lines), ret[2] == Concat(lines))
После обработки (из extraction_trace):
pre и post совпадают с raw
validation = ["postcondition/constraints fail Z3 type check"]
```

**safe_repair, HTTP 0185, T=0.0.**
 В промпте — исходная сигнатура и контекст, правила упрощённого фрагмента и просьба сохранить частичную формулу; список ошибок предыдущей проверки отдельно не передан.

```text
args = ["lines"]
return_type = Tuple[int, int, str]
pre = ["Length(lines) > 0"]
post = And(ret[0] == Length(lines[0]), ret[1] == Length(lines), ret[2] == Concat(lines))
После обработки (из extraction_trace):
pre и post совпадают с raw
validation = ["postcondition/constraints fail Z3 type check"]
```

**Итог и сравнение.**

```text
pre = []
post = ret == ret
degraded = True sanitize_after_validation_failure
oracle = unclassified · formula_parse_error: Non-sequence passed as a sequence
diagnostics = null; counterexample = null (разбор завершился до solver)
```

[Архив с HTTP, prompts и результатом слота](../artifacts/dev-2026-11-22-vpn.tar.gz)

Три ответа сохранили `ret[2] == Concat(lines)`; последний заменил `Length(lines) >= 1` на эквивалентное для длины `Length(lines) > 0`. Fallback убрал это предусловие. Ошибка проверки типов генерации охватывает весь контракт. Отдельно проверка сравнения эталона с собой идентифицирует конкретный сбой: `ret[2]` имеет тип Int вместо String. В изолированном oracle позиционные поля позволяют разобрать gold и отвергнуть неверную высоту. Для `Concat(lines)` даже при корректном типе поля остаётся ошибка арности. Зонд предварительной типизации отдельно показал, почему salvage не сохранил корректные конъюнкты о ширине и высоте в этом ответе. На неровной карте спор о gold сохраняется. [Проверка типов](#exp-tuple) · [Проверка отдельных конъюнктов](#exp-char) · [Запуск Python](#exp-python)

<a id="trace-next-departure"></a>

### `next_departure`. Следующее отправление и вклад двух дополнительных успехов

Код использует остаток от деления, чтобы найти минимальный кратный момент не раньше `min_time`. Gold дополнительно требует неотрицательное время.
[Python-вход](../../../benchmark/lifted_auto_eval/python_by_contract_correct_aoc2020_day_13_shuttle_search.py_next_departure.py) · [Gold YAML](../../../benchmark/lifted/python_by_contract_correct_aoc2020_day_13_shuttle_search.py_next_departure.yaml)

Эталон, поля, которые читает scorer.

```text
pre = ["min_time >= 0", "bus_id > 0"]
post = And(ret >= min_time, ret < min_time + bus_id, ret % bus_id == 0)
```

**Слот** `python_by_contract::correct::aoc2020::day_13_shuttle_search.py::next_departure:code:treatment:1`. HTTP: `0124.json` (200).

Фрагмент входа модели из HTTP-записи с сигнатурой и предметным контекстом.

```text
Signature:
next_departure(bus_id: int, min_time: int) -> int

Function source:
def next_departure(bus_id: int, min_time: int) -> int:
    """Compute the next departure of ``bus_id`` leaving earliest at ``min_time``."""
    missed_last_bus_by = min_time % bus_id
    if missed_last_bus_by == 0:
        return min_time
    else:
        return min_time - missed_last_bus_by + bus_id

Additional context:
```

**initial, HTTP 0124, T=0.7.**

```text
args = ["bus_id", "min_time"]
return_type = int
pre = ["bus_id > 0"]
post = And(ret >= min_time, ret % bus_id == 0, ret - min_time < bus_id)
После обработки (из extraction_trace):
pre и post совпадают с raw
validation = []
```

**Итог и сравнение.**

```text
pre = ["bus_id > 0"]
post = And(ret >= min_time, ret % bus_id == 0, ret - min_time < bus_id)
degraded = False
oracle = non_equivalent · case_pre_spec
solver_status = {"pre_mismatch_check": "sat", "pre_spec_implies_pre_code": "unsat", "pre_code_implies_pre_spec": "sat"}
well_formedness = ok
counterexample = {"bus_id": 1, "min_time": -1}
```

Других логических вызовов в слоте нет. Repair, safe repair и salvage не выполнялись.

[Архив с HTTP, prompts и результатом слота](../artifacts/dev-2026-11-22-vpn.tar.gz)


**Слот** `python_by_contract::correct::aoc2020::day_13_shuttle_search.py::next_departure:code:treatment:3`. HTTP: `0126.json` (200), `0127.json` (200), `0128.json` (200).

Фрагмент входа модели из HTTP-записи с сигнатурой и предметным контекстом.

```text
Signature:
next_departure(bus_id: int, min_time: int) -> int

Function source:
def next_departure(bus_id: int, min_time: int) -> int:
    """Compute the next departure of ``bus_id`` leaving earliest at ``min_time``."""
    missed_last_bus_by = min_time % bus_id
    if missed_last_bus_by == 0:
        return min_time
    else:
        return min_time - missed_last_bus_by + bus_id

Additional context:
```

**initial, HTTP 0126, T=0.7.**

```text
args = ["bus_id", "min_time"]
return_type = int
pre = ["bus_id > 0"]
post = ret == min_time - (min_time % bus_id) + If(min_time % bus_id == 0, 0, bus_id)
После обработки (из extraction_trace):
post → ret == min_time - min_time % bus_id + If(min_time % bus_id == 0, 0, bus_id)
validation = ["postcondition/constraints fail Z3 type check"]
```

**repair, HTTP 0127, T=0.0.**
 В промпте `Errors to fix` = `["postcondition/constraints fail Z3 type check"]`, затем нормализованный первый JSON в `Current invalid JSON`.

```text
args = ["bus_id", "min_time"]
return_type = int
pre = ["bus_id > 0"]
post = ret == min_time - (min_time % bus_id) + If(min_time % bus_id == 0, 0, bus_id)
После обработки (из extraction_trace):
post → ret == min_time - min_time % bus_id + If(min_time % bus_id == 0, 0, bus_id)
validation = ["postcondition/constraints fail Z3 type check"]
```

**safe_repair, HTTP 0128, T=0.0.**
 В промпте — исходная сигнатура и контекст, правила упрощённого фрагмента и просьба сохранить частичную формулу; список ошибок предыдущей проверки отдельно не передан.

```text
args = ["bus_id", "min_time"]
return_type = int
pre = ["bus_id > 0", "min_time >= 0"]
post = And(ret >= min_time, ret % bus_id == 0, ret - min_time < bus_id)
После обработки (из extraction_trace):
pre и post совпадают с raw
validation = []
```

**Итог и сравнение.**

```text
pre = ["bus_id > 0", "min_time >= 0"]
post = And(ret >= min_time, ret % bus_id == 0, ret - min_time < bus_id)
degraded = True recovered_safe_subset
oracle = equivalent · equivalent_no_mismatch
solver_status = {"pre_mismatch_check": "unsat", "pre_spec_implies_pre_code": "unsat", "pre_code_implies_pre_spec": "unsat", "post_mismatch_check": "unsat"}
well_formedness = ok
counterexample = null
```

[Архив с HTTP, prompts и результатом слота](../artifacts/dev-2026-11-22-vpn.tar.gz)

Слот 1 восстановил кратность и длину интервала, но оказался шире gold по домену. Слот 3 дошёл до safe repair, в котором появилось `min_time >= 0`. После нормализации и проверки он получил эквивалентность. Слот 2 (HTTP 0125) по коду также пропустил это предусловие, а слот 4 (0129–0131) получил эквивалентность после safe repair. Для двух успехов из четырёх вероятность случайной подвыборки составляет 1/2, 5/6 и 1 при k=1, 2 и 4. Кодовый baseline также эквивалентен. Свидетель Z3 с отрицательным временем принадлежит более широкому домену кандидата; поставляемый Python на нём определён. Чтобы отдельно оценить восстановление постусловия, можно заранее согласовать сравнение на общем домене, сохранив строгий verdict как основную оценку. [Запуск Python](#exp-python)

<a id="trace-duration"></a>

### `duration`. Длительность, включение последнего дня и скрытый домен

Текст сообщает о вычислении длительности пребывания. Код явно добавляет 1. Gold требует упорядоченного интервала и инклюзивного подсчёта. Блок дополнительного контекста пуст в обоих каналах.
[Python-вход](../../../benchmark/lifted_auto_eval/python_by_contract_correct_ethz_eprog_2019_exercise_05_problem_04.py_Entry_duration.py) · [Gold YAML](../../../benchmark/lifted/python_by_contract_correct_ethz_eprog_2019_exercise_05_problem_04.py_Entry_duration.yaml)

Эталон, поля, которые читает scorer.

```text
pre = ["self_end >= self_start"]
post = ret == self_end - self_start + 1
```

**Слот** `python_by_contract::correct::ethz_eprog_2019::exercise_05::problem_04.py::Entry::duration:spec:treatment:1`. HTTP: `0253.json` (200).

Фрагмент входа модели из HTTP-записи с сигнатурой и предметным контекстом.

```text
Signature:
duration(self_start: int, self_end: int) -> int

Informal specification:
Compute the duration of the stay.

Additional context:
```

**initial, HTTP 0253, T=0.7.**

```text
args = ["self_start", "self_end"]
return_type = int
pre = ["self_start <= self_end"]
post = ret == self_end - self_start
После обработки (из extraction_trace):
pre и post совпадают с raw
validation = []
```

**Итог и сравнение.**

```text
pre = ["self_start <= self_end"]
post = ret == self_end - self_start
degraded = False
oracle = non_equivalent · case_post_code
solver_status = {"pre_mismatch_check": "unsat", "pre_spec_implies_pre_code": "unsat", "pre_code_implies_pre_spec": "unsat", "post_mismatch_check": "sat", "spec_post_implies_code_post": "sat", "code_post_implies_spec_post": "sat"}
well_formedness = ok
counterexample = {"self_start": 0, "self_end": 0}
post_mismatch_check witness = {"self_start": 0, "self_end": 0, "ret": 1}
```

Других логических вызовов в слоте нет. Repair, safe repair и salvage не выполнялись.

[Архив с HTTP, prompts и результатом слота](../artifacts/dev-2026-11-22-vpn.tar.gz)


**Слот** `python_by_contract::correct::ethz_eprog_2019::exercise_05::problem_04.py::Entry::duration:code:treatment:1`. HTTP: `0258.json` (200).

Фрагмент входа модели из HTTP-записи с сигнатурой и предметным контекстом.

```text
Signature:
duration(self_start: int, self_end: int) -> int

Function source:
def duration(self_start: int, self_end: int) -> int:
    """Compute the duration of the stay."""
    return self_end - self_start + 1

Additional context:
```

**initial, HTTP 0258, T=0.7.**

```text
args = ["self_start", "self_end"]
return_type = int
pre = []
post = ret == self_end - self_start + 1
После обработки (из extraction_trace):
pre и post совпадают с raw
validation = []
```

**Итог и сравнение.**

```text
pre = []
post = ret == self_end - self_start + 1
degraded = False
oracle = non_equivalent · case_pre_spec
solver_status = {"pre_mismatch_check": "sat", "pre_spec_implies_pre_code": "unsat", "pre_code_implies_pre_spec": "sat"}
well_formedness = ok
counterexample = {"self_start": 0, "self_end": -1}
```

Других логических вызовов в слоте нет. Repair, safe repair и salvage не выполнялись.

[Архив с HTTP, prompts и результатом слота](../artifacts/dev-2026-11-22-vpn.tar.gz)

В описании получилась формула без `+1` при правильном домене. По коду получилась формула с `+1` без предусловий. Обе приняты сразу и повторились во всех пяти слотах своих каналов. Равные даты в архивном контрпримере показывают расхождение постусловий. Перевёрнутый интервал в кодовом случае показывает расхождение предусловий; oracle прекращает основную проверку до этапа сравнения постусловий. Локальный вызов функции на перевёрнутом интервале возвращает 0. Следующий эксперимент — предзарегистрировать отдельное условие с доменным контекстом из исходного проекта и сравнить предусловия при прежнем oracle и равном бюджете. [Запуск Python](#exp-python)

<a id="trace-solve"></a>

### `solve`. Первое нарушение условия окна, Optional и расхождение gold с кодом

Функция ищет первое число, которое нельзя представить суммой двух различных значений из предшествующего окна. Она возвращает индекс во всём списке и число либо None. Gold требует первое нарушение по двум различным позициям, разрешая одинаковые значения на этих позициях.
[Python-вход](../../../benchmark/lifted_auto_eval/python_by_contract_correct_aoc2020_day_9_encoding_error.py_solve.py) · [Gold YAML](../../../benchmark/lifted/python_by_contract_correct_aoc2020_day_9_encoding_error.py_solve.yaml)

Эталон, поля, которые читает scorer.

```text
pre = ["Length(puzzle_input) > preamble_length", "preamble_length > 0"]
post = Or(And(ret == None, ForAll([k], Implies(And(preamble_length <= k, k < Length(puzzle_input)), Exists([i], And(0 <= i, i < preamble_length, Exists([j], And(0 <= j, j < preamble_length, i != j, puzzle_input[k - preamble_length + i] + puzzle_input[k - preamble_length + j] == puzzle_input[k]))))))), And(Not(ret == None), preamble_length <= ret[0], ret[0] < Length(puzzle_input), ret[1] == puzzle_input[ret[0]], Not(Exists([i], And(0 <= i, i < preamble_length, Exists([j], And(0 <= j, j < preamble_length, i != j, puzzle_input[ret[0] - preamble_length + i] + puzzle_input[ret[0] - preamble_length + j] == ret[1]))))), ForAll([k], Implies(And(preamble_length <= k, k < ret[0]), Exists([i], And(0 <= i, i < preamble_length, Exists([j], And(0 <= j, j < preamble_length, i != j, puzzle_input[k - preamble_length + i] + puzzle_input[k - preamble_length + j] == puzzle_input[k]))))))))
```

**Слот** `python_by_contract::correct::aoc2020::day_9_encoding_error.py::solve:code:treatment:1`. HTTP: `0239.json` (200), `0240.json` (200), `0241.json` (200).

Фрагмент входа модели из HTTP-записи с сигнатурой и предметным контекстом.

```text
Signature:
solve(puzzle_input: List[int], preamble_length: int) -> Optional[Tuple[int, int]]

Function source:
def solve(puzzle_input: List[int], preamble_length: int) -> Optional[Tuple[int, int]]:
    """
    Parse the data of the XMAS protocol, ``puzzle_input``, and find a weakness.

    :return:
        offset of the number,
        first number *after* the preamble which uncovers the weakness
    """
    for index, number in enumerate(puzzle_input[preamble_length:]):
        preamble = puzzle_input[index : index + preamble_length]
        valid = False
        for i in preamble:
            for j in preamble:
                if i != j and i + j == number:
                    valid = True
        if not valid:
            return preamble_length + index, number

    return None

Additional context:
```

**initial, HTTP 0239, T=0.7.**

```text
args = ["puzzle_input", "preamble_length"]
return_type = Optional[Tuple[int, int]]
pre = ["preamble_length >= 0", "Length(puzzle_input) >= preamble_length"]
post = Exists([k], And(0 <= k, k < Length(puzzle_input) - preamble_length, Not(Exists([i, j], And(0 <= i, i < preamble_length, 0 <= j, j < preamble_length, i != j, puzzle_input[k + i] + puzzle_input[k + j] == puzzle_input[k + preamble_length]))), ret == (k, puzzle_input[k + preamble_length])))
После обработки (из extraction_trace):
post → Exists([k], And(0 <= k, k < Length(puzzle_input) - preamble_length, Not(Exists([i, j], And(0 <= i, i < preamble_length, 0 <= j, j < preamble_length, i != j, puzzle_input[k + i] + puzzle_input[k + j] == puzzle_input[k + preamble_length]))), And(ret[0] == k, ret[1] == puzzle_input[k + preamble_length])))
validation = ["postcondition/constraints fail Z3 type check"]
```

**repair, HTTP 0240, T=0.0.**
 В промпте `Errors to fix` = `["postcondition/constraints fail Z3 type check"]`, затем нормализованный первый JSON в `Current invalid JSON`.

```text
args = ["puzzle_input", "preamble_length"]
return_type = Optional[Tuple[int, int]]
pre = ["preamble_length >= 0", "Length(puzzle_input) >= preamble_length"]
post = Or(Length(ret) == 0, And(Length(ret) == 2, Exists([k], And(0 <= k, k < Length(puzzle_input) - preamble_length, ret[0] == k, ret[1] == puzzle_input[k + preamble_length], Not(Exists([i, j], And(0 <= i, i < preamble_length, 0 <= j, j < preamble_length, i != j, puzzle_input[k + i] + puzzle_input[k + j] == puzzle_input[k + preamble_length]))), ForAll([k2], Implies(And(0 <= k2, k2 < k), Exists([i, j], And(0 <= i, i < preamble_length, 0 <= j, j < preamble_length, i != j, puzzle_input[k2 + i] + puzzle_input[k2 + j] == puzzle_input[k2 + preamble_length]))))))))
После обработки (из extraction_trace):
pre и post совпадают с raw
validation = ["postcondition/constraints fail Z3 type check"]
```

**safe_repair, HTTP 0241, T=0.0.**
 В промпте — исходная сигнатура и контекст, правила упрощённого фрагмента и просьба сохранить частичную формулу; список ошибок предыдущей проверки отдельно не передан.

```text
args = ["puzzle_input", "preamble_length"]
return_type = Optional[Tuple[int, int]]
pre = ["preamble_length >= 0", "Length(puzzle_input) >= preamble_length"]
post = Or(Length(ret) == 0, And(Length(ret) == 2, ret[0] >= preamble_length, ret[0] < Length(puzzle_input), ret[1] == puzzle_input[ret[0]], Not(Exists([i], And(0 <= i, i < preamble_length, Exists([j], And(0 <= j, j < preamble_length, i != j, puzzle_input[ret[0] - preamble_length + i] + puzzle_input[ret[0] - preamble_length + j] == ret[1]))))))))
После обработки (из extraction_trace):
pre и post совпадают с raw
validation = ["postcondition invalid expression syntax: unmatched ')' (<unknown>, line 1)"]
```

**Итог и сравнение.**

```text
pre = []
post = ret == ret
degraded = True sanitize_after_validation_failure
oracle = non_equivalent · case_pre_spec
solver_status = {"pre_mismatch_check": "sat", "pre_spec_implies_pre_code": "unsat", "pre_code_implies_pre_spec": "sat"}
well_formedness = ok
counterexample = {"puzzle_input": "Empty(Seq(Int))", "preamble_length": 0}
```

[Архив с HTTP, prompts и результатом слота](../artifacts/dev-2026-11-22-vpn.tar.gz)

В первом ответе `k` отсчитывается от начала поиска и сохраняется в `ret[0]`; исходная функция добавляет `preamble_length`. Формула с `Exists([k], ...)` не ограничивает предыдущие окна и не описывает ветку None. Нормализация разложила равенство кортежу по позициям. Repair попытался выразить обе ветки, но получил общее сообщение type check. Safe repair содержит лишнюю скобку. В fallback исчезли оба исходных условия `preamble_length >= 0` и `Length(puzzle_input) >= preamble_length`. Первое из них само было слабее gold. Oracle отверг итог на пустом входе с окном 0, раньше содержательного сравнения поиска. В Python-опыте `[5,5,10], 2` получен другой свидетель: две пятёрки на разных позициях допустимы для gold, но исключены оператором сравнения значений в Python. Контроль для следующей версии — проверять отсутствие результата, абсолютный индекс, минимальность индекса и позиционную семантику на окнах с дубликатами. [Запуск Python](#exp-python)

<a id="trace-swap"></a>

### `swap`. Успешное восстановление перестановки

Функция возвращает пару в обратном порядке. Gold связывает обе выходные позиции с входными и задаёт пустой список предусловий.
[Python-вход](../../../benchmark/lifted_auto_eval/crosshair_examples_PEP316_correct_code_arith.py_swap.py) · [Gold YAML](../../../benchmark/lifted/crosshair_examples_PEP316_correct_code_arith.py_swap.yaml)

Эталон, поля, которые читает scorer.

```text
pre = []
post = ret[0] == things[1] and ret[1] == things[0]
```

**Слот** `crosshair_examples::PEP316::correct_code::arith.py::swap:code:treatment:1`. HTTP: `0009.json` (200), `0010.json` (200).

Фрагмент входа модели из HTTP-записи с сигнатурой и предметным контекстом.

```text
Signature:
swap(things: Tuple[int, int]) -> Tuple[int, int]

Function source:
def swap(things: Tuple[int, int]) -> Tuple[int, int]:
    """
    Swap the arguments.

    post: _[0] == things[1]
    post: _[1] == things[0]
    """
    return (things[1], things[0])

Additional context:
```

**initial, HTTP 0009, T=0.7.**

```text
args = ["things"]
return_type = Tuple[int, int]
pre = []
post = ret[0] == things[1] And ret[1] == things[0]
После обработки (из repair-промпта):
pre и post совпадают с raw
validation = ["postcondition uses infix And/Or", "postcondition invalid expression syntax: invalid syntax (<unknown>, line 1)"]
```

**repair, HTTP 0010, T=0.0.**
 В промпте `Errors to fix` = `["postcondition uses infix And/Or", "postcondition invalid expression syntax: invalid syntax (<unknown>, line 1)"]`, затем нормализованный первый JSON в `Current invalid JSON`.

```text
args = ["things"]
return_type = Tuple[int, int]
pre = []
post = And(ret[0] == things[1], ret[1] == things[0])
Промежуточная запись validation отсутствует. Принятие ответа видно по выходу и числу вызовов.
```

**Итог и сравнение.**

```text
pre = []
post = And(ret[0] == things[1], ret[1] == things[0])
degraded = False
oracle = equivalent · equivalent_no_mismatch
solver_status = {"pre_mismatch_check": "unsat", "pre_spec_implies_pre_code": "unsat", "pre_code_implies_pre_spec": "unsat", "post_mismatch_check": "unsat"}
well_formedness = ok
counterexample = null
```

Safe repair и salvage не выполнялись. Успешный обычный repair заменил payload. В архивном нативном трейсе остался только `final`, а полная запись второго ответа видна в HTTP.

[Архив с HTTP, prompts и результатом слота](../artifacts/dev-2026-11-22-vpn.tar.gz)

Первый ответ указывает правильные равенства, но соединяет их инфиксным `And`. Обычный repair заменил запись на вызов `And(...)`; затем формула прошла сравнение. В raw JSON обоих ответов `args=["things"]`. В сохранённом ExtractionResult добавилось имя `int]`: штатный разбор делит строку сигнатуры по запятой внутри аннотации. Gold scoring строит типизированный контекст по эталону, поэтому в этом слоте посторонний элемент метаданных не изменил verdict. Следующая проверка для исправления этой ошибки — разобрать аннотацию синтаксически и сверить список аргументов, затем убедиться, что прежняя формула сохраняет эквивалентность. [Зонд аргументов](#exp-char)

<a id="diagnostics"></a>

## 6. Дополнительные диагностические эксперименты

Во всех проверках использовались только dev-данные и локальные Python 3.14.4 и Z3 4.16.0.0 из указанного checkout. Таймаут solver 5000 мс сохранён. Новых вызовов Groq не было. Изолированные изменения применялись в памяти Python и исчезали при выходе из блока `patch`. Артефакты исторического запуска образуют исходную точку сравнения. Команды приведены в [приложении](#reproduce).

<a id="exp-scores"></a>

### Дополнительный диагностический эксперимент 1. Агрегаты и повторная оценка 100 финалов

**Пробел.** Для `csv_first_column:code` историческое поле `task_metrics` содержало два treatment-`unknown`, а поле `scores` — четыре. Проверялась гипотеза о том, что расхождение видно на уровне конкретных статусов, а формула агрегации даёт однозначный результат для выбранного журнала. Сначала проверили 100 уникальных slot ID и хеши dev-входов, пересчитали `c/u`, метрики и затраты из raw записей. Затем снова вызвали исходный gold scorer для каждого финала, перехватывая штатную блокировку для каждого слота с непроверяемым эталоном ради диагностического подсчёта. Этот способ оставляет неизменным официальный gate. Seeds относятся только к split и bootstrap, оба `20261120`; bootstrap включает 10 000 переотборов. [Архив](../artifacts/dev-2026-11-22-vpn.tar.gz) · [Код стандартного gate](../../../src/dualify/rq1_report.py#L179-L234)

**Результат.** Повторены все 100 статусов, исходные причины и этапы проверки там, где они присутствовали в архиве. Для `unclassified` сравнивалось вложенное поле `reason`, для классифицированных исходов также сравнивался `well_formedness`. В `csv_first_column` все пять кодовых исходов остались `solver_unknown_pre`. Три исхода по описанию остались `solver_unknown_post`, два — `solver_unknown_pre`. Архивные поля solver status дают этап отказа. Сохранённой причины из `reason_unknown()` нет. Новый проход не установил причину исторического различия. [Архив](../artifacts/dev-2026-11-22-vpn.tar.gz) · [RQ1-013](../../agent/KNOWN_BUGS.md)

Для фиксированного пула `p_k(s) = 1 − C(4−s,k)/C(4,k)`, где `s=c` в нижнем сценарии и `s=c+u` в верхнем. Вероятность считается по равновероятным подмножествам слотов без возвращения. Переход к вероятности будущих генераций требует предпосылок о независимости и одинаковом распределении. Разность `p_4(c+u) − p_1(c+u)` относится к сценарию, в котором успешны все `unknown`. Она сама по себе не даёт верхней границы прироста: при двух успехах из четырёх прирост меньше, чем при одном. Отдельно парный bootstrap переотбирает девять задач и вычисляет нижнюю оценку и её разность из одних и тех же задач. Он не моделирует зависимость между родственными задачами и неопределённость новых пулов. [Протокол](../RQ1.md#6-статистическая-оценка-и-формулы) · [Chen и др., 2021](https://arxiv.org/abs/2107.03374)

| Канал | Нижние pass@1/2/4 | При успехе всех unknown | 95% интервалы нижних pass@1 / pass@4 / разности 4−1 |
| --- | --- | --- | --- |
| Описание | 11,1 / 11,1 / 11,1% | 22,2 / 22,2 / 22,2% | [0; 33,3]% / [0; 33,3]% / [0; 0] п.п. |
| Код | 16,7 / 20,4 / 22,2% | 27,8 / 31,5 / 33,3% | [0; 38,9]% / [0; 55,6]% / [0; 16,7] п.п. |

В расчёт вошли девять оценённых задач. В фиксированном порядке первых *k* слотов доля задач с подтверждённым успехом по описанию составляет 1/9, 1/9, 1/9, по коду — 1/9, 1/9, 2/9. Это диагностика порядка слотов. При усреднении по всем одиночным слотам нижний кодовый pass@1 равен 16,7%. Совпадение всех четырёх финальных формул в пяти пулах по описанию и шести по коду относится к строковому представлению. В тех же пулах выходило в среднем 9,22 и 9,89 логических вызовов на четыре попытки. Повторный подсчёт raw HTTP дал 243 уникальных completion ID, 251 857 входных и 51 113 выходных токенов на 243 успешных ответа. Это подтверждает отдельные обращения и объём наблюдаемой работы. Время клиента включает минимальный интервал между запросами и backoff. [Рисунок pass@k](../figures/dev-pass-at-k.png) · [Рисунок задержек](../figures/dev-latency.png) · [Архив](../artifacts/dev-2026-11-22-vpn.tar.gz)

<a id="exp-tuple"></a>

### Дополнительный диагностический эксперимент 2. Смешанный кортеж и контроль неверной высоты

**Гипотеза.** Если исключение на gold вызвано сортом третьего поля, сохранение позиционных типов достаточно для self-check и оставляет проверку чувствительной к неправильной формуле. В исходной конфигурации сравнили каждый из десяти dev-эталонов с самим собой. Затем локально заменили представление только точной аннотации `Tuple[int, int, str]` на `z3.TupleSort` с доступом к трём полям через позиционные селекторы. Применили это в основном и вспомогательном scorer. Контрольный контракт меняет только `ret[1] == Length(lines)` на `ret[1] == Length(lines) + 1`. Дополнительный контроль взял из `0183` формулу с `Concat(lines)`. В той же изоляции пересчитали десять сохранённых финалов `parse_input`. Seed неприменим. [Gold YAML](../../../benchmark/lifted/python_by_contract_correct_aoc2020_day_3_toboggan_trajectory.py_parse_input.yaml) · [Код типов](../../../src/dualify/phases/p03_smt_checking.py#L51-L88)

**Результат.** В исходной конфигурации девять self-check эквивалентны, `parse_input` возвращает `formula_parse_error: Non-sequence passed as a sequence`. С позиционными типами эталон даёт `equivalent_no_mismatch`, а контрольная неверная высота — `case_post_code`. При независимом переводе `Concat(lines)` с настоящим ID задачи Z3Py возвращает `At least two arguments expected.` Изменение сорта устраняет сбой разбора gold в этом зонде. Оно не превращает `Concat` в операцию склеивания переменного числа строк и не исправляет доменное допущение. В альтернативной кодировке все десять финалов `parse_input` получили `non_equivalent / case_pre_spec`. Пример свидетеля — пустой список строк. В этом опыте увеличилась проверяемость одной задачи. Полный набор dev альтернативным oracle не пересчитывался. Изменение общего переводчика затронуло бы и этап генерации, поэтому сравнение oracle следует сначала проводить на фиксированных финалах. [Зонд в приложении](#reproduce) · [Z3 Datatypes](https://microsoft.github.io/z3guide/docs/theories/Datatypes/)

<a id="exp-char"></a>

### Дополнительный диагностический эксперимент 3. Char и предварительная типизация

**Гипотеза.** В архивном CSV-repair `0059` удаление одного запрета пропустит AST, а дальнейшая проверка либо примет те же формулы, либо покажет независимое препятствие. Сначала прогнали точный архивный post через штатный нормализатор и два валидатора. Затем добавили `Char` в их списки разрешённых имён, сохранив вход и остальные правила. После этого отдельно проверили, что происходит при пустом ID задачи в используемой ими функции `extraction_parseable`. Синтетический отрицательный контроль содержит `And(ret >= 0, ret)` при целочисленном `ret`. Разбор сигнатуры `swap` проверили непосредственно в обоих каналах. Seed неприменим. [Архив, HTTP 0059](../artifacts/dev-2026-11-22-vpn.tar.gz) · [Валидатор](../../../src/dualify/phases/p02_code_to_logic.py#L115-L134) · [Канонизация](../../../src/dualify/phases/p03_smt_checking.py#L118-L164)

**Результат.** После разрешения `Char` проверка выражения проходит в обоих каналах, однако предварительная типизация всего контракта по-прежнему отклоняет его. Её пустой `benchmark_id` включается в регулярное выражение замены вызова функции на `ret`. Например, `identifier[0] == Char('L')` канонизируется в `identifier[0] == Charret`. Если для пустого ID отключить этот эффект подстановкой нейтрального непустого имени, предварительный type-check архивного контракта `0059` проходит. На одном и том же интерфейсе `extraction_parseable` отрицательный контроль даёт `True` при штатной канонизации и `False` после подстановки нейтрального непустого ID. Это подтверждает возможность как ложного отказа, так и пропуска неверного выражения в предварительной проверке. Для `0126` один непустой ID ситуацию не исправляет, а в исходном тексте отдельно срабатывает текстовая проверка наличия охраны знаменателя. Разбор сигнатуры `swap` непосредственно дал `['things', 'int]']` в обоих каналах. [Зонд в приложении](#reproduce) · [Правила предварительной проверки](../../../src/dualify/phases/p03_smt_checking.py#L285-L336)

Для `parse_input` проверили три верхнеуровневых конъюнкта safe-ответа `0185` тем же type-check, который используется в salvage. Два равенства, `ret[0] == Length(lines[0])` и `ret[1] == Length(lines)`, отклонялись в исходном режиме и прошли после подстановки непустого ID. При пустом ID оба вызова `Length` заменялись именем `Lengthret`. Третий конъюнкт с `Concat(lines)` остался неподходящим. Это локализует потерю ширины и высоты в проверке частей формулы. Исторический extractor целиком с изменёнными правилами не перезапускался. [HTTP 0185 и итог](#trace-parse-input)

Оба изменения в CSV проверены только на одной сохранённой формуле. Они ничего не устанавливают о первой запятой, семантической эквивалентности или общем эффекте на pass@k. Для исправления extractor нужны раздельные сравнения и отрицательные контроли. Исторические пути repair остаются фактом. [Трейс CSV](#trace-csv-first-column)

<a id="exp-python"></a>

### Дополнительный диагностический эксперимент 4. Заданные входы Python и смысл gold

**Гипотеза.** Ряд verdict относится к точному домену и профилю gold. Если вызов поставляемого Python на заданном входе даст иной результат или исключение, расхождение можно локализовать независимо от вывода модели и oracle. Использованы только dev-файлы из `preflight.dev_cases` и записанные ниже входы. Seed неприменим.

| Вход | Фактическое поведение Python | Сравнение с эталоном |
| --- | --- | --- |
| `solve([5,5,10], 2)` | `(2, 10)` | В gold на двух разных позициях стоят 5 и 5. В данном окне сумма достижима, поэтому эталон требует ветку None. |
| `parse_input(["..", "#"])` | `(2, 2, "..#")` | Gold требует длину 4, хотя допускает непустой список без требования равной длины строк. |
| `extract_expression("(()")` | `Exception: I should never end up here!` | Выполняются записанные условия о начале, закрывающей скобке и длине. Баланс остаётся вне gold-предусловия. [Gold YAML](../../../benchmark/lifted/python_by_contract_correct_aoc2020_day_18_operation_order.py_extract_expression.yaml) |
| `average([1., 3.])` | `2.0` | Gold допускает весь интервал [1, 3]. Это пример более слабого профиля, без противоречия результату Python. |
| `next_departure(1, -1)`, `duration(0, -1)` | `-1`, `0` | Gold исключает эти входы. Они помогают интерпретировать свидетель расхождения доменов. |

Эти запуски проверяют поведение на конкретных входах. Общая спецификация прикладного домена остаётся решением исследования. В архивном scorer по `solve` сравнение финальной заглушки остановилось на предусловии, поэтому проверка дубликатов — отдельное доказательство о gold и Python. [Исходные входы и эталоны](#trace-solve) · [Реестр расхождений](../../agent/KNOWN_DUALIFY_LIMITATIONS.md)

<a id="exp-csv"></a>

### Дополнительный диагностический эксперимент 5. Фиксированный вход для неизвестного результата CSV

**Гипотеза.** `unknown` в сохранённой проверке по коду может скрывать расхождение уже на простом входе. Во всех пяти кодовых финалах записано предусловие `ForAll([i], Implies(0 <= i, And(i < Length(lines), Contains(lines[i], ','))))`. При `i = Length(lines)` условие `0 <= i` выполняется, а `i < Length(lines)` ложно. В gold верхняя граница входит в условие импликации, поэтому пустой список допускается. Зонд использует финал `csv_first_column:code:treatment:1` (HTTP 0073–0075), исходный перевод формул с типом `List[str]` и обычный лимит Z3. После подстановки `lines = Empty(Seq(String))` проверяет выполнимость `G ∧ ¬C`. Seed неприменим. [Точный код подстановки](#reproduce) · [Эталон CSV](../../../benchmark/lifted/crosshair_examples_icontract_correct_code_showcase.py_csv_first_column.yaml) · [Сохранённый финал](../artifacts/dev-2026-11-22-vpn.tar.gz)

**Результат.** На фиксированном входе solver вернул `sat`. Это отдельная проверка направления расхождения предусловий с заранее выбранным свидетелем. Исторический общий запрос без фиксации входа по-прежнему воспроизводится как `solver_unknown_pre`. Здесь сценарий «все unknown успешны» иллюстрирует чувствительность метрики к статусам. Одинаковые формулы пяти слотов имеют один и тот же найденный дефект. В канале описания два финала с пустым предусловием принимают, например, `["abc"]`, чего gold не допускает; это логический пример по формулам. Ранее приведённый пример с `["a,b"]` и `["x"]` поясняет расхождение других трёх spec-финалов. Эти spec-примеры не выдавались историческим solver. [Трейс CSV](#trace-csv-first-column) · [Статусы поштучного журнала](../artifacts/dev-2026-11-22-vpn.tar.gz)

## 7. Предлагаемые изменения и контроль сравнимости

| Наблюдение и причина | Изменение и проверка | Ожидаемое влияние и риск |
| --- | --- | --- |
| 10 исходов без классификации из-за одного gold, а в CSV `unknown` зафиксирован на проверках предусловий и постусловий | До нового запуска утвердить политику для статусов и собирать единую таблицу из одного прогона. Прогнать штатный scorer по сохранённым финалам и показать покрытие, нижние оценки, сценарии и причины. При отдельной диагностике сохранять `reason_unknown()` с теми же настройками. | Станет видно, какую часть задач реально сравнили и насколько неопределённость меняет результат. Условный знаменатель подвержен смещению. Другой таймаут создаёт отдельное условие проверки. |
| Позиционный сорт исправляет self-check одного эталона | Сравнить исходный oracle и альтернативный перевод типов на одних и тех же сохранённых финалах после проверки отрицательного контроля. Сохранить переходы между статусами и проследить случаи, где нормализация предполагает последовательность. | Возможен рост покрытия проверки. Рост эквивалентности допускается лишь как изменение измерителя. Если перевод изменит предварительную валидацию, причинный эффект новой генерации требует отдельного сравнения. |
| Нормализатор вводит запрещённый `Char`, предварительный parser искажает формулы с пустым ID | Проверить отдельно исправление списка вызовов, затем отдельным условием канонизацию и булев тип предиката. Проверять положительные и отрицательные примеры, включая `0059`, `And(ret >= 0, ret)` и наличие двух запятых. | Часть полезных предикатов может дойти до проверки. Новый тракт генерации меняет вход в repair. Replay сохранённых формул показывает локальный эффект без оценки новых ответов модели. |
| Fallback удаляет точный домен в `average`, а часть контекста отсутствует в `duration` и `determine_column` | Сначала сравнить адресный repair с обычными повторными попытками при одном бюджете логических вызовов. Контекст helper или инвариантов исследовать в отдельном условии. Зафиксировать model ID, температуру, доступный контекст для сравнения repair, oracle и dev-слоты. | Измерять долю прошедших проверку ответов, сохранность известных условий, заглушки, подтверждённую эквивалентность и вызовы. Сравнение потребует новых генераций. Переход к другому prompt снижает сопоставимость с исходной программой без параллельного контроля. |
| Слабы или спорны отдельные gold-свойства | Согласовать основной профиль и отдельно показать поведенческие свидетели на dev. При утверждении другого gold определить домен и версию до новых запросов, затем сравнить старое и новое правило на тех же финалах. | Изменится исследовательская цель. Рост согласия с новым gold следует интерпретировать через выбранные свойства и домен. |

Исходная оценка нужна для сопоставимости. Изменение генератора следует проверять при фиксированном oracle, а изменение oracle — на одних и тех же финальных контрактах. Если правка используется в обоих местах, эти эффекты оцениваются последовательно. Held-out остаётся вне выбора конфигурации. [Протокол](../RQ1.md) · [Отложенный этап](../tickets/heldout-test-and-report-deferred.md)

## 8. Влияние на дипломные RQ1–RQ3

**RQ1** проверяет наличие эквивалентного gold кандидата. В dev показан конечный выигрыш только по коду `next_departure`. Отдельные ошибки измерителя мешают оценке по полному набору. На часть результатов влияет профиль gold или недостающий контекст. Сначала нужно согласовать измеряемую величину и воспроизвести её на архиве. [Границы RQ1](../RQ1.md)

**RQ2** зафиксирован как выбор кандидата без gold. Низкое разнообразие и отсутствие доказанно эквивалентных контрактов ограничивают потенциальный результат выбора. Сравнение selector с контрольной попыткой и с доступностью успеха в пуле — предложение. Для него нужно заранее определить доступные признаки, право отказа и единый внешний критерий. Gold доступен только при итоговой оценке. [Дипломный RQ1, Out of Scope](../RQ1.md#out-of-scope)

**RQ3** зафиксирован как fine-tuning, в RQ1 упоминается PEFT. В качестве гипотезы можно проверить, учится ли модель выдавать формулы поддерживаемого фрагмента, сохраняя поведение. Типы, ошибки переводчика, непроверяемый или спорный gold останутся отдельными факторами оценки. Чтобы интерпретировать обучение, понадобятся независимые данные, раздельная оценка синтаксической пригодности и семантики и фиксированная версия oracle. Отдельные утверждённые гипотезы и методики RQ2/RQ3 в дипломных документах не обнаружены. Нумерация gold fidelity и stability/replay в унаследованном README относится к исходной работе Dualify. [Границы дипломного протокола](../RQ1.md#out-of-scope) · [Унаследованная таблица benchmark](../../../README.md#benchmark-suites-forked-by-experiment)

## 9. Вопросы научному руководителю

### Решения, блокирующие переход к held-out

| Вопрос | Варианты и последствия |
| --- | --- |
| Какой вывод нужен от RQ1? | Сохранить строгую эквивалентность текущему gold для сопоставимости. Приоритет поведения Python потребует определения допустимого входа, профиля свойств и самостоятельной валидизации эталона. |
| Как трактовать `parse_input`, `solve` и `extract_expression`? | Оставить действующие эталоны и объяснить ограничения либо согласовать новый профиль домена и эталонов. Второй путь потребует отдельной версии измерения. В обоих вариантах сохранить исторический результат. |
| Как учитывать `unknown` и непроверяемый gold? | Оставить gate блокирующим либо заранее утвердить условную метрику с покрытием и границами по полному набору. Определить минимальное покрытие для интерпретации и порядок разбора расхождений между оценками. |
| Допустима ли новая версия перевода Z3? | Сохранить оригинальный oracle в основном сравнении и использовать альтернативу для диагностики либо утвердить альтернативу как новый измеритель. Перед этим сверить фиксированные финалы и проверки на заведомом расхождении. |
| Каковы условия допуска к held-out? | Зафиксировать измеритель, версии gold, отчёт по dev, бюджет и правила retry. После выполнения заранее согласованных критериев получить отдельное разрешение на запуск. [Отложенный план](../tickets/heldout-test-and-report-deferred.md) |

### Решения об объёме следующих экспериментов

| Вопрос | Варианты и последствия |
| --- | --- |
| Нужно ли исправлять p01/p02 в рамках диплома? | Сохранение исходного алгоритма даёт вывод об оригинальном Dualify. Исправление `Char`, предварительной типизации или политики repair становится новой экспериментальной веткой. Выбрать одно изменение и сравнить при равном бюджете. |
| Какого выигрыша достаточно для нескольких попыток? | Согласовать минимально содержательный прирост при известном числе вызовов. Можно оставить RQ1 описательным и показывать прирост вместе с затратами и неопределённостью. |
| Какой контекст разрешён модели? | Оставить исходный фрагмент либо отдельно добавить независимый от gold контекст helper/инвариантов. Второй вариант меняет входное условие эксперимента. |
| Нужен ли RQ2 в текущем объёме? | Если нужен один возвращаемый контракт, зафиксировать критерии выбора без gold и измерять качество выбранного контракта. Если изучаем доступность кандидата, достаточно метрики RQ1. |
| Какую гипотезу обучения проверять в RQ3? | Можно предложить обучение формату DSL или семантической точности. Эти задачи требуют разных данных и проверок. Сначала определить, какую ошибку должна устранить модель и как отделить эффект обучения от изменений oracle. |

<a id="reproduce"></a>

## Приложение. Команды воспроизведения

Из корня репозитория в окружении с зафиксированными зависимостями:

```bash
export RQ1_WORK=$(mktemp -d)
tar -xzf docs/rq1/artifacts/dev-2026-11-22-vpn.tar.gz -C "$RQ1_WORK"
export RQ1_ARCHIVE="$RQ1_WORK/rq1-dev-vpn-2026-11-22"
export RQ1_DEV_GOLD="$RQ1_WORK/gold"
mkdir "$RQ1_DEV_GOLD"
poetry run python - <<'PY'
import hashlib, json, os, shutil
from pathlib import Path

archive = Path('docs/rq1/artifacts/dev-2026-11-22-vpn.tar.gz')
freeze = json.loads(archive.with_name('dev-2026-11-22-vpn-freeze.json').read_text())
assert hashlib.sha256(archive.read_bytes()).hexdigest() == freeze['archive_sha256']
root = Path(os.environ['RQ1_ARCHIVE'])
meta = json.loads((root / 'preflight.json').read_text())
for dev in meta['dev_cases']:
    shutil.copy2(dev['gold_path'], os.environ['RQ1_DEV_GOLD'])
PY
```

Для чтения полного запроса и ответа укажите ID из нужного трейса, например `0059`.

```bash
poetry run python - "$RQ1_ARCHIVE/http/0059.json" <<'PY'
import json, sys
from pathlib import Path

record = json.loads(Path(sys.argv[1]).read_text())
print(record['slot_id'], record['status'])
for message in record['payload']['messages']:
    print(message['role'], message['content'])
print(json.dumps(json.loads(record['body']), ensure_ascii=False, indent=2))
PY
```

Сохраните следующий Python-блок как `$RQ1_WORK/verify.py`. Запуск эксперимента 1 по зафиксированным статусам — `poetry run python "$RQ1_WORK/verify.py"`.

```python
import hashlib
import json
import os
from collections import Counter
from math import comb
from pathlib import Path
from random import Random
from statistics import mean, median, quantiles

root = Path(os.environ['RQ1_ARCHIVE'])
meta = json.loads((root / 'preflight.json').read_text())
diag = json.loads((root / 'offline-diagnostics.json').read_text())
scores = diag['scores']
records = {j['slot_id']: j for p in (root / 'pools').rglob('result.json')
           if (j := json.loads(p.read_text()))}
assert len(scores) == len(records) == len(set(meta['planned_slots'])) == 100
assert set(records) == set(meta['planned_slots']) == {s['slot_id'] for s in scores}
for dev in meta['dev_cases']:
    for kind in ('input', 'gold'):
        assert hashlib.sha256(Path(dev[kind + '_path']).read_bytes()).hexdigest() == dev[kind + '_sha256']
print('status', Counter(s['status'] for s in scores))
print('reason', Counter(s['reason'] for s in scores if s['status'] != 'unclassified'))
print('degraded', Counter(r['extraction']['degraded_reason'] for r in records.values()))
print('degraded equivalent', sum(records[s['slot_id']]['extraction']['degraded'] and s['status']=='equivalent' for s in scores))
print('calls & median', Counter(len(records[s['slot_id']]['calls']) for s in scores),
      sum(len(records[s['slot_id']]['calls']) for s in scores), sum(len(r['calls'])-1 for r in records.values()),
      median(records[s['slot_id']]['elapsed_seconds'] for s in scores))
print('by calls', [median(records[s['slot_id']]['elapsed_seconds'] for s in scores if len(records[s['slot_id']]['calls'])==n) for n in (1,2,3)])
http = [json.loads(p.read_text()) for p in (root / 'http').glob('*.json')]
ok = [json.loads(h['body']) for h in http if h['status'] == 200]
print('HTTP', Counter(h['status'] for h in http), len({h['id'] for h in ok}),
      [sum(h['usage'][k] for h in ok) for k in ('prompt_tokens','completion_tokens')],
      median(h['usage']['total_time'] for h in ok))
def rate(s, k):
    return 1 - comb(4-s, k) / comb(4,k)

for channel in ('spec', 'code'):
    rows = []
    calls = []
    dup = []
    first = {k: 0 for k in (1, 2, 4)}
    for dev in meta['dev_cases']:
        pool = [s for s in scores if s['slot_id'].startswith(dev['benchmark_id'] + ':' + channel + ':treatment:')]
        states = Counter(s['status'] for s in pool)
        if states['unclassified']:
            continue
        c, u = states['equivalent'], states['inconclusive']
        rows.append((c, u))
        for k in first:
            first[k] += any(s['status'] == 'equivalent' and
                            int(s['slot_id'].rsplit(':', 1)[1]) <= k for s in pool)
        forms = [(tuple(sorted(e['domain_constraints'])), e['postcondition']) for s in pool
                 if (e := records[s['slot_id']]['extraction'])]
        dup.append(len(set(forms)))
        calls.append(sum(len(records[s['slot_id']]['calls']) for s in pool))
    baseline = Counter(s['status'] for s in scores
                       if s['slot_id'].endswith(f':{channel}:baseline:0'))
    print(channel, rows, 'all equal', dup.count(1), 'duplicates', sum(4-d for d in dup),
          'calls', sum(calls), 'first-k', first, 'baseline', baseline)
    for k in (1,2,4):
        print(k, mean(rate(c,k) for c,u in rows), mean(rate(c+u,k) for c,u in rows))
    samples = Random(20261120)
    triples = [(rate(c,1),rate(c,4),rate(c,4)-rate(c,1)) for c,u in rows]
    draws = [[mean(col) for col in zip(*samples.choices(triples,k=len(rows)))] for _ in range(10000)]
    print('CI', [(q[0],q[-1]) for col in zip(*draws) if (q := quantiles(col,n=40,method='inclusive'))])
```

Сохраните следующий блок как `$RQ1_WORK/probes.py`. Команда `RQ1_FULL_RESCORE=1 poetry run python "$RQ1_WORK/probes.py"` повторяет сравнение 100 финалов и затем эксперименты 2–5. Для запуска только экспериментов 2–5 используйте `RQ1_FULL_RESCORE=0`.

```python
import ast
import json
import os
import runpy
from collections import Counter
from pathlib import Path
from unittest.mock import patch

import z3
from dualify import relation
from dualify.gold_scoring import _case_spec_for_gold, _extraction_from_gold, load_gold_benchmark, score_extraction_against_gold
from dualify.phases import p01_spec_to_logic as p01, p02_code_to_logic as p02, p03_smt_checking as smt
from dualify.rq1_pool import read_candidate_pool
from dualify.rq1_report import AnalysisBlockedError, _candidate
from dualify.formula_parser import normalize_formula

root = Path(os.environ['RQ1_ARCHIVE'])
meta = json.loads((root/'preflight.json').read_text())
gold_files = {d['benchmark_id']: d for d in meta['dev_cases']}
golds = load_gold_benchmark(Path(os.environ['RQ1_DEV_GOLD']), require_unique_ids=True)
scores = json.loads((root/'offline-diagnostics.json').read_text())['scores']
def reason_code(row):
    if row['status'] == 'unclassified':
        return json.loads(row['reason'].split(': unclassified: ',1)[1])['reason']
    return row['reason']

statuses = {s['slot_id']: (s['status'], reason_code(s),
                           s.get('well_formedness') if s['status'] != 'unclassified' else None)
            for s in scores}
print('versions:', z3.get_full_version(), flush=True)
def score(gold, extraction):
    case = _case_spec_for_gold(gold.benchmark_id, gold)
    r = score_extraction_against_gold(case_spec=case, gold=gold, extraction=extraction,
                                     include_diagnostics=True)
    return r.reason, r.pre_relation, r.post_relation

if os.environ.get('RQ1_FULL_RESCORE') == '1':
    counts = Counter()
    differences = []
    for pool in sorted((root/'pools').iterdir()):
        config, records = read_candidate_pool(pool)
        for attempt in records:
            g = golds[attempt.extraction.benchmark_id]
            try:
                r = _candidate(attempt, g)
                actual = (r['status'], r['reason'], r['well_formedness'])
            except AnalysisBlockedError:
                actual = ('unclassified', score(g, attempt.extraction)[0], None)
            counts[actual[0]] += 1
            if actual != statuses[attempt.slot_id]:
                differences.append((attempt.slot_id, statuses[attempt.slot_id], actual))
    print('all:', counts, 'changed:', differences, flush=True)

from dataclasses import replace
for g in golds.values():
    print('self:', g.qualname, score(g, _extraction_from_gold(g)), flush=True)
g = next(g for g in golds.values() if g.qualname=='parse_input')
ref = _extraction_from_gold(g)
wrong = replace(ref, postcondition=ref.postcondition.replace('ret[1] == Length(lines)',
                                                             'ret[1] == Length(lines) + 1'))
print('original sort:', smt._sort_for_type(g.return_type))
sort, constructor, projections = z3.TupleSort('ProbeMap', [z3.IntSort(), z3.IntSort(), z3.StringSort()])
class IndexableTuple(z3.DatatypeRef):
    def __getitem__(self, index):
        return projections[index](self)
original = smt._make_var
def make_var(name, annotation):
    if annotation != 'Tuple[int, int, str]':
        return original(name, annotation)
    value = z3.Const(name, sort)
    return IndexableTuple(value.as_ast(), value.ctx)
def raw(id_):
    http = json.loads((root/f'http/{id_}.json').read_text())
    return json.loads(json.loads(http['body'])['choices'][0]['message']['content'])
with patch.object(smt, '_make_var', make_var), patch.object(relation, '_make_var', make_var):
    print('tuple:', score(g, ref), score(g, wrong))
    print('tuple/183:', smt.extraction_parseable(g.arg_types, g.return_type,
                                                raw('0183')['domain_constraints'],
                                                raw('0183')['postcondition']))
    try:
        smt._safe_eval('Concat(lines)', {'lines': smt._make_var('lines', 'List[str]')}, g.benchmark_id)
    except Exception as error:
        print('concat:', error)

    pool = next((root / 'pools').glob('*parse_input'))
    _, parse_records = read_candidate_pool(pool)
    parse_scores = [_candidate(record, g) for record in parse_records]
    print('tuple/parse_input finals:',
          Counter((row['status'], row['reason']) for row in parse_scores),
          parse_scores[0]['counterexample'])

sample = raw('0059')
post = normalize_formula(sample['postcondition'])
for phase in (p01,p02):
    print(phase.__name__, phase._validate_expression(post, {'lines','ret'}))
    with patch.object(phase, '_ALLOWED_CALLS', phase._ALLOWED_CALLS | {'Char'}):
        print('allowed:', phase._validate_expression(post, {'lines','ret'}),
              phase._typecheck_errors(sample['domain_constraints'],post,{'lines':'List[str]'},'List[str]'))
    print('swap args:', phase._extract_signature_args('swap(things: Tuple[int, int]) -> Tuple[int, int]'))
example = raw('0126')
print('departure source safety:', smt._validate_formula_safety(replace(ref,
      postcondition=normalize_formula(example['postcondition']),
      domain_constraints=example['domain_constraints'])))

for name, args in [('solve', ([5,5,10],2)), ('parse_input', (['..','#'],)),
                   ('next_departure',(1,-1)), ('duration',(0,-1)), ('average',([1.,3.],)),
                   ('extract_expression',('(()',))]:
    path = next(d['input_path'] for bid, d in gold_files.items() if bid.endswith('::'+name))
    try:
        print('behavior:', name, runpy.run_path(path)[name](*args))
    except Exception as error:
        print('behavior:', name, type(error).__name__, str(error))

print('canonicalized:', smt._canonicalize_expression("identifier[0] == Char('L')", ''))
print('char parser actual id:', smt.extraction_parseable({'lines':'List[str]'},'List[str]',
                                                         sample['domain_constraints'],post))
with patch.object(smt, '_rewrite_expression',
                  lambda expr, bid, original=smt._rewrite_expression: original(expr, bid or '__offline_probe__')):
    print('char parser nonempty id:', smt.extraction_parseable({'lines':'List[str]'},'List[str]',
                                                              sample['domain_constraints'],post))
    print('departure 0126 nonempty id:', smt.extraction_parseable({'bus_id':'int','min_time':'int'},'int',
                                                                  example['domain_constraints'],
                                                                  example['postcondition']))
print('departure 0126 native:', smt._canonicalize_expression(example['postcondition'], ''))
post_bad = 'And(ret >= 0, ret)'
arg_types = {'x': 'int'}
print('ill-typed control, empty ID:', smt.extraction_parseable(arg_types, 'int', [], post_bad))
rewrite = smt._rewrite_expression
with patch.object(smt, '_rewrite_expression', lambda expr, bid: rewrite(expr, bid or '__offline_probe__')):
    print('ill-typed control, nonempty ID:', smt.extraction_parseable(arg_types, 'int', [], post_bad))

parse_payload = raw('0185')
post_ast = ast.parse(parse_payload['postcondition'], mode='eval').body
assert isinstance(post_ast, ast.Call)
for part in post_ast.args:
    term = ast.unparse(part)
    native = smt.extraction_parseable({'lines': 'List[str]'}, parse_payload['return_type'], [], term)
    with patch.object(smt, '_rewrite_expression', lambda expr, bid: rewrite(expr, bid or '__offline_probe__')):
        guarded = smt.extraction_parseable({'lines': 'List[str]'}, parse_payload['return_type'], [], term)
    print('parse_input salvage conjunct:', term, native, guarded)

g = next(g for g in golds.values() if g.qualname == 'csv_first_column')
pool = next((root / 'pools').glob('*csv_first_column'))
_, records = read_candidate_pool(pool)
attempt = next(r for r in records if r.slot_id.endswith(':code:treatment:1'))
lines = smt._make_var('lines', g.arg_types['lines'])
scope = {'lines': lines}
gold_pre, candidate_pre = [
    z3.And(*(smt._safe_eval(expr, scope, g.benchmark_id) for expr in pre))
    for pre in (g.domain_constraints, attempt.extraction.domain_constraints)
]
empty_lines = z3.Empty(lines.sort())
solver = z3.Solver()
solver.add(z3.substitute(z3.And(gold_pre, z3.Not(candidate_pre)), (lines, empty_lines)))
print('CSV fixed input []:', smt._check_with_status(solver))
```
