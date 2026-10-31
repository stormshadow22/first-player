import asyncio
import json
import time

import httpx
import pytest
from fastapi.testclient import TestClient

from app import pipeline
from app.dedup import Deduplicator
from app.llm import CallBudget, calls_var, complete, set_client
from app.main import app
from app.schemas import TriageRequest, TriageResponse
from scripts.predict import predict, ticket_request


def test_contract_and_validation():
    with TestClient(app) as client:
        assert client.get("/health").status_code == 200
        for kind, text in [
            ("complaint", "Игрок нарушает 2.1"),
            ("unknown", ""),
            ("report", "x" * 1_000_000),
        ]:
            response = client.post(
                "/triage",
                json={
                    "kind": kind,
                    "messages": [{"role": "player", "text": text, "attachments": 2}],
                },
            )
            assert response.status_code == 200
            result = TriageResponse.model_validate(response.json())
            assert result.needs_human
            assert result.confidence == 0
            assert result.draft_reply.cited == []
        assert (
            client.post(
                "/triage",
                json={
                    "kind": "report",
                    "messages": [{"role": "player", "text": "a", "attachments": -1}],
                },
            ).status_code
            == 422
        )


@pytest.mark.parametrize(
    "module,attr",
    [
        ("normalize", "normalize_text"),
        ("normalize", "detect_lang"),
        ("extract", "extract_facts"),
        ("classify", "classify"),
        ("rag", "retrieve_rules"),
        ("rag", "similar_replies"),
        ("rag", "all_rule_ids"),
        ("generate", "generate_draft"),
        ("guard", "apply_guards"),
    ],
)
async def test_every_component_failure_is_safe(monkeypatch, module, attr):
    def broken(*args):
        raise RuntimeError("test failure")

    monkeypatch.setattr(getattr(pipeline, module), attr, broken)
    result = await pipeline.triage(TriageRequest(kind="report", messages=[]))
    assert result.needs_human
    assert any(attr.replace("_text", "") in r or module in r for r in result.reasons)


async def test_deadline(monkeypatch):
    async def slow(*args):
        await asyncio.sleep(10)

    monkeypatch.setattr(pipeline.generate, "generate_draft", slow)
    started = time.monotonic()
    result = await pipeline.triage(TriageRequest(kind="report", messages=[]))
    assert time.monotonic() - started < 4.7
    assert result.needs_human
    assert "generate_draft:TimeoutError" in result.reasons


def test_dedup_event_window():
    dedup = Deduplicator(event_time=True)
    req = TriageRequest(
        kind="report",
        messages=[],
        reporter_hash="a",
        reported_hash="b",
        created_at="2026-10-30T00:00:00Z",
    )
    assert not dedup.check(req, "one player problem", "unknown")
    assert dedup.check(req, "one player problem", "unknown")
    assert not dedup.check(
        req.model_copy(update={"created_at": "2026-10-30T02:00:00Z"}),
        "one player problem",
        "unknown",
    )
    assert not dedup.check(
        req.model_copy(update={"reporter_hash": "other"}), "one player problem", "unknown"
    )


async def test_predict_bad_lines_and_mapping(tmp_path):
    source, dest = tmp_path / "in.jsonl", tmp_path / "out.jsonl"
    ticket = {
        "ticket_id": 12,
        "kind": "report",
        "images_count": 3,
        "messages": [
            {"role": "admin", "text": "secret answer"},
            {"role": "player", "text": "help"},
        ],
    }
    req = ticket_request(ticket)
    assert len(req.messages) == 1 and req.messages[0].attachments == 3
    source.write_text(json.dumps(ticket) + "\nBROKEN\n", encoding="utf-8")
    stats = await predict(str(source), str(dest), 2)
    assert stats == {"processed": 1, "invalid": 1}
    row = json.loads(dest.read_text(encoding="utf-8"))
    assert row.pop("ticket_id") == 12
    TriageResponse.model_validate(row)


async def test_llm_provider_and_timeout(monkeypatch):
    for k, v in {
        "LLM_PROVIDER": "openai_compatible",
        "LLM_MODEL": "test",
        "LLM_API_KEY": "test",
        "LLM_PRICE_IN_PER_MTOK": "0.1",
        "LLM_PRICE_OUT_PER_MTOK": "0.4",
    }.items():
        monkeypatch.setenv(k, v)
    monkeypatch.delenv("LLM_MOCK", raising=False)

    async def handler(request):
        assert request.url.path == "/v1/chat/completions"
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "ok"}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5},
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        set_client(client)
        token = calls_var.set(CallBudget())
        try:
            result = await complete("system", "user", 100, 1)
            assert result.text == "ok" and result.cost_usd == pytest.approx(0.000003)
            with pytest.raises(RuntimeError):
                await complete("system", "user", 100, 1)
        finally:
            calls_var.reset(token)
            set_client(None)

    async def slow(request):
        await asyncio.sleep(1)

    async with httpx.AsyncClient(transport=httpx.MockTransport(slow)) as client:
        set_client(client)
        token = calls_var.set(CallBudget())
        try:
            with pytest.raises(TimeoutError):
                await complete("system", "user", 100, 0.02)
        finally:
            calls_var.reset(token)
            set_client(None)


async def test_llm_anthropic_cache(monkeypatch):
    for k, v in {
        "LLM_PROVIDER": "anthropic",
        "LLM_MODEL": "test",
        "LLM_API_KEY": "test",
        "LLM_PRICE_IN_PER_MTOK": "0.1",
        "LLM_PRICE_OUT_PER_MTOK": "0.4",
        "LLM_PROMPT_CACHE": "1",
    }.items():
        monkeypatch.setenv(k, v)
    monkeypatch.delenv("LLM_MOCK", raising=False)

    async def handler(request):
        body = json.loads(request.content)
        assert body["system"][0]["cache_control"]["type"] == "ephemeral"
        assert request.headers["anthropic-version"] == "2023-06-01"
        return httpx.Response(
            200,
            json={
                "content": [{"type": "text", "text": "safe"}],
                "usage": {
                    "input_tokens": 10,
                    "cache_read_input_tokens": 20,
                    "cache_creation_input_tokens": 5,
                    "output_tokens": 2,
                },
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        set_client(client)
        token = calls_var.set(CallBudget())
        try:
            result = await complete("s", "u", 10, 1)
            assert result.in_tokens == 35 and result.text == "safe"
        finally:
            calls_var.reset(token)
            set_client(None)


async def test_batch_gzip_dedup(monkeypatch, tmp_path):
    import gzip

    monkeypatch.setenv("DEDUP_ENABLED", "1")
    source, dest = tmp_path / "in.jsonl.gz", tmp_path / "out.jsonl"
    with gzip.open(source, "wt", encoding="utf-8") as f:
        for i in range(3):
            f.write(
                json.dumps(
                    {
                        "ticket_id": i,
                        "kind": "report",
                        "reporter_hash": "player",
                        "created_at": "2026-10-30T00:00:00Z",
                        "messages": [{"role": "player", "text": "same problem"}],
                    }
                )
                + "\n"
            )
    await predict(str(source), str(dest), 2)
    rows = sorted(
        (json.loads(line) for line in dest.read_text(encoding="utf-8").splitlines()), key=lambda r: r["ticket_id"]
    )
    assert [r["is_spam_or_duplicate"] for r in rows] == [False, True, True]
