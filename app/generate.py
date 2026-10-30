"""Participant C integration stub; remaining budget is app.llm.remaining_budget()."""

from app.schemas import ClassResult, DraftResult, Extracted, ReplyExample, RuleHit, TriageRequest


def generate_draft(
    req: TriageRequest,
    facts: Extracted,
    cls: ClassResult,
    rules: list[RuleHit],
    examples: list[ReplyExample],
    lang: str,
) -> DraftResult:
    return DraftResult(lang=lang, text="Обращение требует проверки сотрудником поддержки.")
