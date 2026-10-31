# Контракт интеграции

Источник типов — app/schemas.py; HTTP OpenAPI доступен на /openapi.json и /docs.
Дополнительные поля запрещены. Версия зафиксирована по переданному проекту:
полного исходного общего блока для независимой сверки в архиве нет.

## Запрос и ответ

TriageRequest: обязательны kind (str), messages (list).
Message: role = player | reported_player | admin, text (str), attachments >=0 (default 0).
Необязательные: server_lang (str/null), rule_refs_raw (str/list[str]/null),
reporter_hash, reported_hash, created_at (str/null).
API принимает три роли, pipeline использует только текст player;
batch дополнительно отфильтровывает остальные роли.

TriageResponse: lang, category (любая строка), priority (p0/p1/p2/p3),
is_spam_or_duplicate, extracted, draft_reply, needs_human, confidence (0..1), reasons.
Extracted: nickname, rule_refs (list[str]), has_evidence, server.
DraftReply: lang, text, cited (list[str]).
Безопасные значения: unknown, p3, confidence=0, needs_human=true, cited=[].

## Сигнатуры

```python
normalize_text(text: str, server_lang: str | None) -> str
detect_lang(text: str, hint: str | None = None) -> str
extract_facts(req: TriageRequest, norm_text: str) -> Extracted
classify(req: TriageRequest, norm_text: str, lang: str) -> ClassResult
retrieve_rules(query: str, lang: str, category: str, k: int = 5) -> list[RuleHit]
similar_replies(query: str, lang: str, category: str, k: int = 3) -> list[ReplyExample]
all_rule_ids() -> set[str]
generate_draft(req, facts, cls, rules, examples, lang) -> DraftResult
apply_guards(req, facts, cls, draft, valid_rule_ids: set[str]) -> GuardResult
rule_text(rule_id: str, lang: str) -> str
async complete(system: str, user: str, max_tokens: int, timeout_s: float) -> LLMResult
```

Принимаются sync/async реализации. Необязательный load_resources() экспортируется
из classify/rag и вызывается один раз до API/batch. remaining_budget() — секунды.
Максимум один вызов LLM: это строже разрешённого максимума одной повторной попытки.
RuleHit: id, title, text, text_i18n (dict[str,str]); ReplyExample: text, lang, category.
Все внутренние модели ClassResult, DraftResult, GuardResult, LLMResult — в schemas.py.
Стоимость и латентность не добавляются в HTTP-контракт.

## Ошибки и бюджеты

Неверная схема входа — 422; пустой текст/неизвестный kind — 200 с безопасным ответом.
Ошибки стадий попадают в reasons и принудительно выставляют needs_human=true.
Общий бюджет 4.5s с резервом для guard/сериализации. Входной текст ограничивается.
Sync-функции выполняются в thread: таймаут прекращает ожидание, но не убивает
произвольный сторонний код. Модули должны соблюдать бюджеты и собственные таймауты;
для тяжёлых CPU-моделей потребуется process worker.

## Дедуп

DEDUP_ENABLED=1, default 0. TTL 60 минут, cosine по парным TF-IDF >=0.85,
максимум 10000 записей на процесс. С reporter_hash ключ reporter+reported+category;
без него сравнение похожего текста внутри категории. HTTP использует текущее время.
Batch использует created_at: сортируйте вход по времени; при битой/отсутствующей
дате дедуп пропускается с предупреждением, тикет остаётся в обработке.
Batch сравнивает тексты в порядке входа в общей категории batch до классификации.
Разные процессы/реплики не разделяют хранилище. Это эвристика, не модерация спама.
