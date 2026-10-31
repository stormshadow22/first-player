# Support Copilot

Бэкенд хакатона: жалоба игрока → классификация → поиск правил → черновик → проверка.
Контракт: `app/schemas.py`. Инфраструктура A готовится к интеграции B/C/D.
Предметные модули пока заглушки: `category="unknown"`, `confidence=0`,
`needs_human=true`, пустые цитаты. Успешный `/health` означает запуск и прогрев
ресурсов, а не качество модели. Реальные данные и полный исходный общий контракт
в репозиторий не включены.

## Windows / PowerShell

Нужны Git и Python 3.11. Выполнять из корня проекта:

```powershell
git clone https://github.com/stormshadow22/first-player.git
cd first-player
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.lock
Copy-Item .env.example .env
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Активация venv и изменение ExecutionPolicy не нужны. При ошибке `py -3.11`
установите/восстановите Python 3.11; Python 3.15 для этого lockfile не подходит.
Откройте http://127.0.0.1:8000/docs → POST /triage → Try it out → Execute.
Пример запроса: `examples/triage.json`. Остановка — Ctrl+C.

```powershell
curl.exe http://127.0.0.1:8000/health
curl.exe -X POST http://127.0.0.1:8000/triage -H "Content-Type: application/json" --data-binary "@examples/triage.json"
```

По умолчанию LLM_MOCK=1: ключ не нужен. Текущий generate.py возвращает локальный
шаблон и сам LLM не вызывает. `.env` автоматически читается Python; переменные
окружения имеют приоритет. Compose также передаёт настройки из `.env`.

## Linux / macOS

```sh
python3.11 -m venv .venv
.venv/bin/python -m pip install -r requirements.lock
cp .env.example .env
.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

При наличии GNU Make: `make install`, `make run`, `make test lint smoke`.
Windows Make необязателен, используйте Python-команды.

## Docker

С запущенным Docker Desktop (Linux containers) или Docker Engine:

```sh
docker compose up --build --wait
```

Открыть http://127.0.0.1:8000/docs. Остановка: `docker compose down`.
Путь к сертификату хоста для обычной сборки не требуется. Тома data и models
доступны read-only, reports/raw сохраняется на хосте. Особенности корпоративного
TLS-прокси описаны в docs/DEVELOPMENT.md.

Если планируете запускать batch/acceptance на Linux-хосте одновременно с
контейнером, заранее создайте каталоги от своего пользователя:
`mkdir -p reports/raw data models`. Это сохраняет права записи для хостовых скриптов.

## Проверки и измерения

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m scripts.smoke
.\.venv\Scripts\python.exe -m scripts.acceptance
```

В Linux замените путь к Python на `.venv/bin/python`.
Acceptance запускает HTTP-сервис, проверяет обычный/пустой/огромный запрос,
неизвестный kind и ошибку валидации, обрабатывает 1000 синтетических тикетов,
проверяет ID/схему каждого ответа и измеряет 400 HTTP-запросов (concurrency=8).
Это проверка инфраструктуры, а не оценка модели.

Отчёты: reports/raw/acceptance.json, bench.json, metrics.json, http-metrics.json.
Задержки — ms, стоимость — USD. CI повторяет проверки на Windows, Linux и Docker;
отчёты сохраняются в Actions artifacts. Сводка локальной проверки — docs/VALIDATION_A.md.

Реальные обращения положите в data, модели/индексы — в models. Не коммитьте их.

```powershell
.\.venv\Scripts\python.exe -m scripts.predict --input data/tickets_valid.jsonl --output reports/raw/pred-valid.jsonl --concurrency 8
.\.venv\Scripts\python.exe -m scripts.acceptance --input data/tickets_valid.jsonl
```

Поддерживается JSONL.GZ. Predict пропускает битые записи с номером строки,
пишет по готовности; порядок не гарантирован. Роли admin/reported_player
отбрасываются, images_count переносится в attachments первого player-сообщения
без умножения. Выход: ticket_id плюс все поля TriageResponse.
Для строгого acceptance нужны >=1000 валидных записей с уникальными ticket_id.

При уже работающем API: `python -m scripts.bench --input data/tickets_valid.jsonl --count 400`.
Запускайте через Python из venv, на одном API worker без посторонней нагрузки.
При p95 > 5000ms или HTTP-ошибках команда завершается с ошибкой; отчёт указывает
средние задержки стадий, самую медленную стадию и её владельца.

## Подключение команды

Ветки от актуального main, изменения через PR:

```sh
git pull --ff-only origin main
git switch -c feature/participant-b
```

- A: схемы, API/pipeline/runtime, LLM-адаптер, predict, bench, CI и Docker.
- B: normalize.py, extract.py, classify.py; добавляет scripts/train_classifier.py.
- C: rag.py, generate.py; добавляет scripts/build_index.py.
- D: guard.py, i18n.py; добавляет scripts/eval.py и тесты качества.

Сигнатуры зафиксированы в docs/CONTRACT.md, схемы менять согласованно.
Make train/index/eval ожидают будущие модули B/C/D и пока намеренно завершаются
ошибкой отсутствующего модуля. Они не имитируют обучение/оценку.
Экспортируйте load_resources() в classify/rag: runtime вызовет его один раз до
HTTP или batch inference. Не загружайте модель на каждом запросе.

Для C: предпочтителен async generate_draft с await app.llm.complete(system, user,
max_tokens, timeout_s). remaining_budget() возвращает оставшиеся секунды.
Максимум один LLM-вызов на тикет. После успешного вызова заполните
DraftResult.llm_used=True, cost_usd и latency_ms из LLMResult.

## Настоящая LLM

В .env.example выбран gpt-5.6-luna с reasoning none и max_completion_tokens.
Официальные цены проверены 31 октября 2026: input $0.20/MTok, output $1.20/MTok,
cached input $0.02/MTok, cache-write 1.25x input. В примере input консервативно
установлен $0.25. Источник: https://developers.openai.com/api/docs/models/gpt-5.6-luna

Перед живым запуском перепроверьте прайс/доступность в аккаунте, задайте ключ и
LLM_MOCK=0. Цены берутся из env. Предварительный лимит $0.002/тикет, общий дедлайн
pipeline 4.5s. Реальную скорость нужно измерить после подключения генератора C.
Другой compatible-провайдер может требовать LLM_TOKEN_LIMIT_FIELD=max_tokens
и отсутствие LLM_REASONING_EFFORT. Адаптер Anthropic поддерживает opt-in caching
через LLM_PROMPT_CACHE=1; задайте цены с учётом cache-write.

Скидки кэша не вычитаются из консервативной оценки. Сетевые ошибки/таймауты могут
тарифицироваться провайдером: фактический bill остаётся источником истины.
Автоматических повторов нет. Ключи и .env не коммитить.

## До финальной сдачи

Интегрировать B/C/D, сверить схемы с полным исходным контрактом, обработать
1000 реальных валидационных тикетов и измерить p95/стоимость готового ядра.
Админка по условию — бонус только после готовности ядра и измерений.
Текст для команды находится в docs/HANDOFF_A.md.
