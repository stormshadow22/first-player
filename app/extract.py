"""Participant B integration stub."""

from app.schemas import Extracted, TriageRequest


def extract_facts(req: TriageRequest, norm_text: str) -> Extracted:
    return Extracted(has_evidence=any(m.attachments > 0 for m in req.messages))
