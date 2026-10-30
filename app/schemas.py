"""Shared wire contract and component result types; coordinate changes with owners."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Priority = Literal["p0", "p1", "p2", "p3"]


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Message(Model):
    role: Literal["player", "reported_player", "admin"]
    text: str
    attachments: int = Field(default=0, ge=0)


class TriageRequest(Model):
    # Unknown kinds deliberately reach the safe fallback rather than crashing.
    kind: str
    messages: list[Message]
    server_lang: str | None = None
    rule_refs_raw: str | list[str] | None = None
    reporter_hash: str | None = None
    reported_hash: str | None = None
    created_at: str | None = None


class Extracted(Model):
    nickname: str | None = None
    rule_refs: list[str] = Field(default_factory=list)
    has_evidence: bool = False
    server: str | None = None


class DraftReply(Model):
    lang: str = "und"
    text: str = ""
    cited: list[str] = Field(default_factory=list)


class TriageResponse(Model):
    lang: str = "und"
    category: str = "unknown"
    priority: Priority = "p3"
    is_spam_or_duplicate: bool = False
    extracted: Extracted = Field(default_factory=Extracted)
    draft_reply: DraftReply = Field(default_factory=DraftReply)
    needs_human: bool = True
    confidence: float = Field(default=0.0, ge=0, le=1)
    reasons: list[str] = Field(default_factory=list)


class ClassResult(Model):
    category: str = "unknown"
    priority: Priority = "p3"
    confidence: float = Field(default=0.0, ge=0, le=1)
    is_spam: bool = False


class RuleHit(Model):
    id: str
    title: str = ""
    text: str = ""
    text_i18n: dict[str, str] = Field(default_factory=dict)


class ReplyExample(Model):
    text: str
    lang: str = "und"
    category: str = "unknown"


class DraftResult(DraftReply):
    cost_usd: float = Field(default=0.0, ge=0)
    latency_ms: float = Field(default=0.0, ge=0)
    llm_used: bool = False


class GuardResult(Model):
    draft: DraftResult = Field(default_factory=DraftResult)
    needs_human: bool = True
    reasons: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.0, ge=0, le=1)


class LLMResult(Model):
    text: str = ""
    in_tokens: int = Field(default=0, ge=0)
    out_tokens: int = Field(default=0, ge=0)
    cost_usd: float = Field(default=0.0, ge=0)
    latency_ms: float = Field(default=0.0, ge=0)
