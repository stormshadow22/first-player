# Проверка участника A, 30 октября 2026

Python 3.11.17, CPU, один Uvicorn worker, HTTP concurrency=8.

- pytest: 16 passed; одна upstream DeprecationWarning Starlette/AnyIO.
- ruff check: passed.
- make install: повторная установка без изменений lockfile прошла.
- make smoke: реальный subprocess, GET /health и POST /triage — passed.
- docker compose up --build -d --wait: сборка и healthcheck прошли.
- HTTP POST к контейнеру: контракт проверен через Pydantic; безопасный ответ.
- make predict IN=/tmp/support-1000.jsonl OUT=reports/raw/pred-1000.jsonl:
  1000/1000 синтетических тикетов, 1000 уникальных ID, все ответы валидны.
- Контейнерный benchmark: 400/400 синтетических тикетов, ошибок 0,
  p50=10.84ms, p95=18.29ms, p99=23.88ms. Стоимость $0/тикет,
  поскольку генератор — локальная заглушка, вызовов LLM нет.
- Исходные измерения: reports/raw/bench.json (игнорируется Git),
  process metrics: reports/raw/metrics.json (экспорт при остановке).

Эти измерения не являются оценкой на tickets_valid.jsonl: данные не предоставлены.
Результат настоящей модели, релевантность правил, качество языка и стоимость
живого LLM не измерены. Не выдавать измеренную стоимость заглушки за стоимость LLM.
API-провайдеры протестированы через httpx.MockTransport; прайс OpenAI вернул 403.

Повторить на реальных данных после интеграции модулей B/C/D:
make predict IN=data/tickets_valid.jsonl OUT=reports/raw/pred-valid.jsonl
.venv/bin/python -m scripts.bench --input data/tickets_valid.jsonl --count 400
Проверить labels category/priority, rules и taxonomy до оценки качества.

Админ-интерфейс не делался: бонус разрешён после готовности предметного ядра.
Сообщение для команды подготовлено в HANDOFF_A.md; подключённого чата нет.
