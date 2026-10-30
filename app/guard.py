"""Participant D conservative integration stub."""

from app.schemas import ClassResult, DraftResult, Extracted, GuardResult, TriageRequest


def apply_guards(
    req: TriageRequest,
    facts: Extracted,
    cls: ClassResult,
    draft: DraftResult,
    valid_rule_ids: set[str],
) -> GuardResult:
    safe = draft.model_copy(update={"cited": []})
    return GuardResult(draft=safe, reasons=["guard_stub: human review required"])
