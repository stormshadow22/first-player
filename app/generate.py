"""Conservative, budget-bounded draft generation with a validated local fallback."""

import asyncio
import json
import logging
import re
import time
from contextvars import ContextVar
from pathlib import Path

from app import llm
from app.fallback import fallback_text
from app.schemas import ClassResult, DraftResult, Extracted, ReplyExample, RuleHit, TriageRequest

logger = logging.getLogger(__name__)
MAX_INPUT_CHARS = 3500
MAX_OUTPUT_TOKENS = 250
TIMEOUT_SECONDS = 3.5
LANGS = {"ru", "kk", "uz", "en", "es", "pt"}
SYSTEM_PROMPT = Path(__file__).with_name("prompts").joinpath("draft_system.txt")
usage_var: ContextVar[tuple[int, int]] = ContextVar("draft_usage", default=(0, 0))


def _contains_unsafe_promise(text: str) -> bool:
    patterns = (
        r"(?i)\b(?:unban(?:ned)?|remove (?:the )?ban|unblock|ban (?:will be|is) removed|ban lifted)\b",
        r"(?i)\b(?:refund|return (?:your )?(?:money|funds)|money back|возврат|верн[её]м деньги|разбан|снимем бан|разблокируем)\b",
        r"(?i)\b(?:will be punished|will get (?:a )?(?:ban|mute)|will punish|получит (?:бан|мут)|будет наказан|накажем игрока|получит наказание)\b",
    )
    boundary = chr(92) + "b"
    multilingual = r"(?i)(?:ақша.{0,15}қайтарам|бан.{0,10}алынады|жазалан|pul.{0,15}qaytar|blokdan chiqar|jazolan|reembols|devolver.{0,15}dinero|ban.{0,12}retirad|será castigad|será punid|dinheiro.{0,12}volta|desban)"
    return bool(re.search(multilingual, text)) or any(re.search(pattern.replace(boundary, ""), text) for pattern in patterns)


def _fallback(lang: str, facts: Extracted, rules: list[RuleHit], query: str) -> DraftResult:
    safe_lang = lang if lang in LANGS else "ru"
    text = fallback_text(safe_lang)
    cited = []
    if rules:
        hit = rules[0]
        templates = {
            "ru": f"Обращение принято на проверку. Указан пункт {hit.id}; сотрудник проверит его применимость.",
            "kk": f"Өтініш тексеруге қабылданды. {hit.id}-тармақтың қолданылуын қызметкер тексереді.",
            "uz": f"Murojaat tekshirish uchun qabul qilindi. Xodim {hit.id}-band qo‘llanishini ko‘rib chiqadi.",
            "en": f"Your report is under review. A moderator will check whether rule {hit.id} applies.",
            "es": f"Tu reporte está en revisión. Un moderador comprobará si se aplica la regla {hit.id}.",
            "pt": f"Sua denúncia está em análise. Um moderador verificará se a regra {hit.id} se aplica.",
        }
        text, cited = templates[safe_lang], [hit.id]
    if facts.nickname:
        text = text.replace(".", f" ({facts.nickname}).", 1)
    if _contains_unsafe_promise(text):
        text, cited = fallback_text(safe_lang), []
    return DraftResult(lang=safe_lang, text=text, cited=cited)


def _parse_json(raw: str) -> dict | None:
    candidates = [raw.strip()]
    match = re.search(r"\{[\s\S]*\}", raw)
    if match:
        candidates.append(match.group(0))
    for candidate in candidates:
        try:
            value = json.loads(candidate)
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(value, dict) and isinstance(value.get("text"), str):
            cited = value.get("cited", [])
            if isinstance(cited, list) and all(isinstance(c, str) for c in cited):
                return {"text": value["text"], "cited": cited}
    return None


def _local_validation(text: str, cited: list[str], rules: list[RuleHit]) -> bool:
    valid_ids = {rule.id for rule in rules}
    references = set(re.findall(r"\b\d+\.\d+\b", text))
    return (
        set(cited) <= valid_ids
        and references <= set(cited)
        and not _contains_unsafe_promise(text)
    )


async def generate_draft(
    req: TriageRequest,
    facts: Extracted,
    cls: ClassResult,
    rules: list[RuleHit],
    examples: list[ReplyExample],
    lang: str,
) -> DraftResult:
    """Use exactly one LLM call; every failure returns a short offline draft."""
    started = time.monotonic()
    usage_var.set((0, 0))
    fallback = _fallback(lang, facts, rules, "")
    allowed_rules = rules[:3]
    # Categories with no rule requirement may legitimately cite nothing.
    from app.rag import categories_need_rules

    rule_required = cls.category in categories_need_rules()
    if rule_required and not allowed_rules:
        return fallback
    if llm.remaining_budget() <= 0.05:
        return fallback
    rule_context = [
        {"id": r.id, "title": r.title, "text": r.text[:500]} for r in allowed_rules
    ]
    example_context = [
        {"lang": e.lang, "category": e.category, "text": e.text[:240]}
        for e in examples[:2]
    ]
    request = {
        "kind": req.kind,
        "category": cls.category,
        "language": lang if lang in LANGS else "ru",
        "player_statement": "\n".join(m.text for m in req.messages if m.role == "player")[:MAX_INPUT_CHARS],
        "nickname": facts.nickname,
        "evidence_attached": facts.has_evidence,
        "rule_refs_claimed_by_player": req.rule_refs_raw,
        "rules": rule_context,
        "style_examples": example_context,
    }
    system = SYSTEM_PROMPT.read_text(encoding="utf-8")
    try:
        timeout = min(TIMEOUT_SECONDS - 0.05, max(0.01, llm.remaining_budget() - 0.05))
        async with asyncio.timeout(timeout):
            result = await llm.complete(
                system,
                json.dumps(request, ensure_ascii=False),
                max_tokens=MAX_OUTPUT_TOKENS,
                timeout_s=timeout,
            )
        usage_var.set((result.in_tokens, result.out_tokens))
        parsed = _parse_json(result.text)
        if parsed is None or (rule_required and not parsed["cited"]) or not _local_validation(parsed["text"], parsed["cited"], allowed_rules):
            logger.warning("Draft output failed JSON or citation safety validation; using template")
            return fallback.model_copy(update={"latency_ms": (time.monotonic() - started) * 1000})
        return DraftResult(
            lang=lang if lang in LANGS else "ru",
            text=parsed["text"],
            cited=sorted(set(parsed["cited"])),
            cost_usd=result.cost_usd,
            latency_ms=result.latency_ms,
            llm_used=True,
        )
    except Exception as exc:
        logger.warning("Draft generation failed (%s); using template", type(exc).__name__)
        return fallback.model_copy(update={"latency_ms": (time.monotonic() - started) * 1000})
