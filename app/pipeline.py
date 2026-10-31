"""Deadline bounded orchestration, with conservative per-stage degradation."""

import asyncio
import inspect
import logging
import os
import time

from app import classify, extract, generate, guard, normalize, rag
from app.dedup import Deduplicator
from app.fallback import fallback_text
from app.llm import CallBudget, calls_var, deadline_var, metrics
from app.schemas import (
    ClassResult,
    DraftReply,
    DraftResult,
    Extracted,
    GuardResult,
    TriageRequest,
    TriageResponse,
)

logger = logging.getLogger(__name__)
service_dedup = Deduplicator()


async def invoke(fn, *args):
    """Support synchronous CPU modules and asynchronous provider integrations."""
    if inspect.iscoroutinefunction(fn):
        return await fn(*args)
    value = await asyncio.to_thread(fn, *args)
    return await value if inspect.isawaitable(value) else value


async def triage(
    req: TriageRequest, *, dedup: Deduplicator | None = None, dedup_enabled: bool | None = None
) -> TriageResponse:
    started = time.monotonic()
    deadline = started + 4.5
    token = deadline_var.set(deadline - 0.10)
    call_budget = CallBudget()
    call_token = calls_var.set(call_budget)
    reasons: list[str] = []

    async def step(name, fn, args, fallback, reserve=0.08):
        step_started = time.monotonic()
        failed = False
        try:
            remaining = deadline - time.monotonic() - reserve
            if remaining <= 0:
                raise TimeoutError()
            return await asyncio.wait_for(invoke(fn, *args), timeout=remaining)
        except Exception as exc:
            failed = True
            logger.warning("Stage %s failed: %s", name, type(exc).__name__)
            reasons.append(f"{name}:{type(exc).__name__}")
            return fallback
        finally:
            metrics.record_stage(name, (time.monotonic() - step_started) * 1000, failed)

    try:
        # Bound model input and memory without treating reported/admin messages as player facts.
        text = "\n".join(m.text[:32000] for m in req.messages if m.role == "player")[:64000]
        if (
            any(len(m.text) > 32000 for m in req.messages)
            or sum(len(m.text) for m in req.messages) > 64000
        ):
            reasons.append("input_truncated")
        if not text.strip():
            reasons.append("empty_text")
        if req.kind not in {"complaint", "report"}:
            reasons.append("unknown_kind")
        text = await step("normalize", normalize.normalize_text, (text, req.server_lang), text)
        lang = await step("detect_lang", normalize.detect_lang, (text, req.server_lang), "und")
        facts = await step("extract", extract.extract_facts, (req, text), Extracted())
        cls = await step("classify", classify.classify, (req, text, lang), ClassResult())
        duplicate = False
        if dedup_enabled if dedup_enabled is not None else os.getenv("DEDUP_ENABLED", "0") == "1":
            duplicate = await step(
                "dedup", (dedup or service_dedup).check, (req, text, cls.category), False
            )
        rules, examples = [], []
        if not (cls.is_spam or duplicate):
            rules = await step("retrieve_rules", rag.retrieve_rules, (text, lang, cls.category), [])
            examples = await step(
                "similar_replies", rag.similar_replies, (text, lang, cls.category), []
            )
        fallback = DraftResult(lang=lang, text=fallback_text(lang))
        draft = await step(
            "generate_draft",
            generate.generate_draft,
            (req, facts, cls, rules, examples, lang),
            fallback,
            reserve=0.15,
        )
        if not draft.llm_used:
            reasons.append("template_fallback")
        ids = await step("all_rule_ids", rag.all_rule_ids, (), set())
        guarded = await step(
            "apply_guards",
            guard.apply_guards,
            (req, facts, cls, draft, ids),
            GuardResult(draft=fallback, reasons=["guard_unavailable"]),
        )
        # Only retrieved, known rules can appear as citations even if a component misbehaves.
        relevant = {r.id for r in rules} & ids
        if any(c not in relevant for c in guarded.draft.cited):
            reasons.append("unverified_citation")
            guarded = GuardResult(draft=fallback, reasons=["citation_rejected"])
        metrics.record_ticket(
            not guarded.draft.llm_used, (time.monotonic() - started) * 1000, call_budget.cost_usd
        )
        return TriageResponse(
            lang=lang,
            category=cls.category,
            priority=cls.priority,
            is_spam_or_duplicate=cls.is_spam or duplicate,
            extracted=facts,
            draft_reply=DraftReply(
                lang=guarded.draft.lang, text=guarded.draft.text, cited=guarded.draft.cited
            ),
            needs_human=guarded.needs_human or bool(reasons),
            confidence=0.0 if reasons else guarded.confidence,
            reasons=reasons + guarded.reasons,
        )
    except Exception as exc:
        logger.exception("Unexpected pipeline failure")
        metrics.record_ticket(True, (time.monotonic() - started) * 1000, call_budget.cost_usd)
        return TriageResponse(reasons=reasons + [f"pipeline:{type(exc).__name__}"])
    finally:
        deadline_var.reset(token)
        calls_var.reset(call_token)
