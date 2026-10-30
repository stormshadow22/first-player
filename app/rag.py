"""Participant C integration stub; never invent rules."""

from app.schemas import ReplyExample, RuleHit


def retrieve_rules(query: str, lang: str, category: str, k: int = 5) -> list[RuleHit]:
    return []


def similar_replies(query: str, lang: str, category: str, k: int = 3) -> list[ReplyExample]:
    return []


def all_rule_ids() -> set[str]:
    return set()
