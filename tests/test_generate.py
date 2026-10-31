import json

import httpx
import pytest

from app import generate, llm
from app.llm import CallBudget
from app.schemas import ClassResult, Extracted, RuleHit, TriageRequest


@pytest.fixture
def context():
    req = TriageRequest(kind="complaint", messages=[{"role": "player", "text": "Оскорбил меня"}])
    return req, Extracted(nickname="Player_1", has_evidence=True), ClassResult(category="complaint.insult"), [RuleHit(id="2.1", text="Оскорбления запрещены.")]


@pytest.mark.parametrize("lang", ["ru", "kk", "uz", "en", "es", "pt"])
async def test_offline_fallback_is_safe_in_supported_languages(monkeypatch, context, lang):
    monkeypatch.setattr(generate, "LANGS", {lang})
    monkeypatch.setattr(generate.llm, "remaining_budget", lambda: 0)
    draft = await generate.generate_draft(*context, [], lang)
    assert draft.cited == ["2.1"]
    assert "2.1" in draft.text
    assert not generate._contains_unsafe_promise(draft.text)
    assert not draft.llm_used


async def test_llm_json_is_one_call_and_valid_citations(monkeypatch, context):
    monkeypatch.setenv("LLM_MOCK", "0")
    monkeypatch.setenv("LLM_PROVIDER", "openai_compatible")
    monkeypatch.setenv("LLM_MODEL", "test")
    monkeypatch.setenv("LLM_API_KEY", "test")
    monkeypatch.setenv("LLM_PRICE_IN_PER_MTOK", "0.1")
    monkeypatch.setenv("LLM_PRICE_OUT_PER_MTOK", "0.4")
    monkeypatch.setenv("LLM_TOKEN_LIMIT_FIELD", "max_tokens")
    seen = []

    async def handler(request):
        seen.append(json.loads(request.content))
        return httpx.Response(200, json={
            "choices": [{"message": {"content": '{"text":"Обращение принято, пункт 2.1 проверят.","cited":["2.1"]}'}}],
            "usage": {"prompt_tokens": 20, "completion_tokens": 10},
        })

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        llm.set_client(client)
        token = llm.calls_var.set(CallBudget())
        try:
            draft = await generate.generate_draft(*context, [], "ru")
        finally:
            llm.calls_var.reset(token)
            llm.set_client(None)
    assert draft.llm_used and draft.cited == ["2.1"]
    assert draft.cost_usd < 0.002
    assert len(seen) == 1


@pytest.mark.parametrize("unsafe", [
    "Разбаним игрока", "Вернём деньги", "Игрок получит мут", "You will be punished",
    "We will refund your money", "Your ban will be removed",
])
def test_unsafe_promises_are_rejected(unsafe):
    assert generate._contains_unsafe_promise(unsafe)
    assert not generate._local_validation(unsafe, [], [RuleHit(id="2.1")])


async def test_invalid_json_and_unknown_citation_fall_back(monkeypatch, context):
    async def bad(*args, **kwargs):
        return llm.LLMResult(text='{"text":"Пункт 99.1 применяется","cited":["99.1"]}')

    monkeypatch.setattr(generate.llm, "complete", bad)
    monkeypatch.setattr(generate.llm, "remaining_budget", lambda: 1)
    draft = await generate.generate_draft(*context, [], "ru")
    assert draft.cited == ["2.1"]
    assert "99.1" not in draft.text
