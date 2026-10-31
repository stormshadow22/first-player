# Сообщение для команды

Репозиторий: https://github.com/stormshadow22/first-player

Каркас A готов к интеграции: схемы, FastAPI /triage, /health, /metrics,
pipeline 4.5s, безопасный fallback, LLM adapter/mock, JSONL/GZIP predict,
benchmark, TF-IDF дедуп, Docker, тесты и CI для Windows/Linux/Docker.
Как запустить — README. Ключ LLM для начала не нужен.

B: замените normalize.py, extract.py, classify.py; добавьте scripts/train_classifier.py.
C: замените rag.py, generate.py; добавьте scripts/build_index.py.
D: замените guard.py, i18n.py; добавьте scripts/eval.py и тесты качества/guard.

Делайте ветки от свежего main и PR. Сигнатуры — docs/CONTRACT.md,
источник схем — app/schemas.py. Изменение контракта согласовывайте с A.
В classify/rag экспортируйте load_resources() для однократной загрузки.
Runtime вызывает её и для HTTP, и для batch. Генератор C лучше async,
с await app.llm.complete. Один вызов LLM на тикет; remaining_budget() — секунды.

Пока B/C/D — заглушки: unknown, confidence=0, needs_human=true, cited=[].
Это ожидаемое поведение. Данные и модели в Git не добавлять. Нужны настоящие
тикеты, rules, taxonomy и полный исходный общий контракт для финальной сверки.
После интеграции A повторяет predict на 1000 валидационных тикетах и benchmark
на 400 тикетах. Админка — бонус после ядра и измерений.

Это подготовленный текст. Канал/адрес команды не предоставлен;
наличие файла не означает, что сообщение отправлено.
