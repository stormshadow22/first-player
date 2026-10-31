import json

import httpx
import pytest
from fastapi.testclient import TestClient

from app import classify, llm, pipeline, rag
from app.dedup import Deduplicator
from app.main import app
from app.schemas import DraftResult, TriageRequest
from scripts.predict import predict


async def test_batch_loads_resources_once(monkeypatch, tmp_path):
    loaded = []
    monkeypatch.setattr(classify, "load_resources", lambda: loaded.append("classifier"), raising=False)
    monkeypatch.setattr(rag, "load_resources", lambda: loaded.append("index"), raising=False)
    source, output = tmp_path / "tickets.jsonl", tmp_path / "pred.jsonl"
    source.write_text("\n".join(json.dumps({"ticket_id": i, "kind": "report", "messages": []}) for i in range(3)), encoding="utf-8")
    assert (await predict(str(source), str(output)))["processed"] == 3
    assert loaded == ["classifier", "index"]


def test_failed_startup_forces_human_review(monkeypatch):
    def broken():
        raise RuntimeError("Missing index")

    monkeypatch.setattr(rag, "load_resources", broken, raising=False)
    with TestClient(app) as client:
        assert client.get("/health").json()["status"] == "degraded"
        result = client.post("/triage", json={"kind": "report", "messages": []}).json()
        assert result["needs_human"]
        assert result["confidence"] == 0
        assert "startup:app.rag:RuntimeError" in result["reasons"]


def test_fuzzy_dedup_without_reporter_and_category_separation():
    dedup = Deduplicator()
    req = TriageRequest(kind="report", messages=[])
    text = "one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen"
    assert not dedup.check(req, text, "category-a")
    assert dedup.check(req, text + " please", "category-a")
    assert not dedup.check(req, text, "category-b")
    assert not dedup.check(req, "a different unrelated problem", "category-a")


async def test_missing_event_time_does_not_drop_ticket(monkeypatch, tmp_path):
    monkeypatch.setenv("DEDUP_ENABLED", "1")
    source, output = tmp_path / "tickets.jsonl", tmp_path / "pred.jsonl"
    source.write_text(json.dumps({"ticket_id": 1, "kind": "report", "messages": [{"role": "player", "text": "help"}]}), encoding="utf-8")
    assert await predict(str(source), str(output)) == {"processed": 1, "invalid": 0}
    result = json.loads(output.read_text(encoding="utf-8"))
    assert result["ticket_id"] == 1
    assert "batch_dedup:invalid_created_at" in result["reasons"]
    assert result["needs_human"]


async def test_llm_cost_survives_guard_failure(monkeypatch):
    metrics = llm.Metrics()
    monkeypatch.setattr(llm, "metrics", metrics)
    monkeypatch.setattr(pipeline, "metrics", metrics)
    for name, value in {
        "LLM_MOCK": "0", "LLM_PROVIDER": "openai_compatible", "LLM_MODEL": "test",
        "LLM_API_KEY": "test", "LLM_PRICE_IN_PER_MTOK": "0.1", "LLM_PRICE_OUT_PER_MTOK": "0.4",
        "LLM_TOKEN_LIMIT_FIELD": "max_completion_tokens", "LLM_REASONING_EFFORT": "none",
    }.items():
        monkeypatch.setenv(name, value)

    async def handler(request):
        body = json.loads(request.content)
        assert body["max_completion_tokens"] == 50
        assert "max_tokens" not in body
        assert body["reasoning_effort"] == "none"
        return httpx.Response(200, json={"choices": [{"message": {"content": "draft"}}], "usage": {"prompt_tokens": 10, "completion_tokens": 5}})

    async def generate(*args):
        result = await llm.complete("system", "user", 50, 1)
        return DraftResult(text=result.text, llm_used=True, cost_usd=result.cost_usd)

    def broken_guard(*args):
        raise ValueError("Guard unavailable")

    monkeypatch.setattr(pipeline.generate, "generate_draft", generate)
    monkeypatch.setattr(pipeline.guard, "apply_guards", broken_guard)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        llm.set_client(client)
        try:
            result = await pipeline.triage(TriageRequest(kind="report", messages=[{"role": "player", "text": "help"}]))
        finally:
            llm.set_client(None)
    snapshot = metrics.snapshot()
    assert result.needs_human
    assert snapshot["fallback_fraction"] == 1
    assert snapshot["ticket_cost_mean_usd"] == pytest.approx(0.000003)
    assert snapshot["stages"]["apply_guards"]["failures"] == 1
