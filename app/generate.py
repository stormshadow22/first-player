"""Participant C integration stub; remaining budget is app.llm.remaining_budget()."""

from app.fallback import fallback_text
from app.schemas import ClassResult, DraftResult, Extracted, ReplyExample, RuleHit, TriageRequest


def generate_draft(
    req: TriageRequest,
    facts: Extracted,
    cls: ClassResult,
    rules: list[RuleHit],
    examples: list[ReplyExample],
    lang: str,
) -> DraftResult:
    return DraftResult(lang=lang, text=fallback_text(lang))
