# Сообщение команде

Каркас Support Copilot готов: контракт в app/schemas.py, POST /triage, GET /health,
безопасные заглушки B/C/D, pipeline с общим дедлайном 4.5s, streaming predict,
LLM adapter, дедупликация, Makefile и Docker. Данные не коммитим.

B: замените normalize.py/extract.py/classify.py; добавьте scripts/train_classifier.py.
C: замените rag.py/generate.py; добавьте scripts/build_index.py.
D: замените guard.py/i18n.py; добавьте scripts/eval.py, README и тесты guard.
Команды make train/index/eval зарезервированы для этих будущих entrypoints;
до появления модулей они завершаются ошибкой, а не имитируют обучение/оценку.

Все публичные сигнатуры из общего блока сохранены. Pipeline поддерживает sync
и async компоненты. Рекомендуется async generate_draft + await app.llm.complete.
Оставшийся бюджет: app.llm.remaining_budget(). Он автоматически ограничивает
complete(timeout_s=...). Повторы отключены: максимум один вызов LLM на тикет.
Внутренние модели, поля которых не были полностью заданы, зафиксированы в schemas.py:
ReplyExample(text, lang, category), RuleHit.text_i18n = dict[lang, text].
Сообщите A перед изменением схем. Если индекс/модель имеет явную загрузку,
экспортируйте load_resources() — lifespan вызовет её и прогреет основные пути.

Без data/rules.json и taxonomy.json классы/правила не изобретаются. Все ответы
пока unknown, confidence=0, needs_human=true, cited=[]. Нельзя считать это
проверенной моделью триажа или демонстрацией качества RAG.

Участник A не получил адрес/канал чата команды; это подготовленный текст,
а не подтверждение отправки в чат.
