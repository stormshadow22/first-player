"""Participant B integration stub; never invent taxonomy labels."""

from app.schemas import ClassResult, TriageRequest


def classify(req: TriageRequest, norm_text: str, lang: str) -> ClassResult:
    return ClassResult()
