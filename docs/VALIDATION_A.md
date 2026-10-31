# Проверка участника A — 31 октября 2026

Python 3.11.18, Windows, один API worker, HTTP concurrency=8.

- pytest: 21 passed; одна upstream DeprecationWarning Starlette/AnyIO.
- ruff check: passed.
- Docker Compose configuration: passed (docker compose config --quiet).
- HTTP smoke: обычный, пустой, огромный запрос и неизвестный kind — валидный ответ; неверная схема — 422.
- Predict: 1000/1000 синтетических тикетов, 1000 уникальных ID, все ответы валидны.
- HTTP benchmark: 400/400, ошибок 0, p50=222.06ms, p95=350.52ms, p99=501.10ms.
- LLM calls: 0. Стоимость 0 USD, потому что генератор — локальная заглушка.
- Отчёты: reports/raw/acceptance.json, bench.json, metrics.json, http-metrics.json (не коммитятся).

Docker Engine недоступен локальной среде (отказ доступа к named pipe).
Проверка сборки и HTTP контейнера вынесена в GitHub Actions; результат см. в CI.

Это синтетическая проверка инфраструктуры. Настоящие валидационные тикеты,
rules/taxonomy и интегрированные модели B/C/D пока отсутствуют. Качество модели,
скорость и стоимость живого LLM не измерены. Полный исходный контракт для
независимой сверки схем не предоставлен. Финальная приёмка на реальных данных
остаётся открытой, её нельзя заменить этими замерами.

Повторить после интеграции: python -m scripts.acceptance --input data/tickets_valid.jsonl
Использовать Python из venv и не менее 1000 записей с уникальными ticket_id.
Модель и официальный прайс сверены в README и .env.example; ключ не предоставлен.
Админка отложена до готовности ядра и метрик по условию задания.
