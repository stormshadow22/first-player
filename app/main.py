"""HTTP service and explicit resource lifecycle."""

import asyncio
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI

from app import classify, rag
from app.llm import metrics, set_client
from app.pipeline import invoke, triage
from app.schemas import TriageRequest, TriageResponse


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with httpx.AsyncClient(limits=httpx.Limits(max_connections=32), timeout=4.0) as client:
        set_client(client)
        app.state.warmup_errors = []
        # Owners may expose load_resources() for actual indexes/models. Warm current lazy paths too.
        for module in (rag, classify):
            loader = getattr(module, "load_resources", None)
            if loader:
                try:
                    await asyncio.wait_for(invoke(loader), 30)
                except Exception as exc:
                    app.state.warmup_errors.append(f"{module.__name__}:{type(exc).__name__}")
        try:
            await asyncio.wait_for(invoke(rag.all_rule_ids), 30)
            await asyncio.wait_for(invoke(rag.retrieve_rules, "", "und", "unknown"), 30)
            await asyncio.wait_for(invoke(rag.similar_replies, "", "und", "unknown"), 30)
            await asyncio.wait_for(
                invoke(classify.classify, TriageRequest(kind="report", messages=[]), "", "und"), 30
            )
        except Exception as exc:
            app.state.warmup_errors.append(type(exc).__name__)
        yield
        metrics.export()
        set_client(None)


app = FastAPI(title="Support Copilot", lifespan=lifespan)


@app.get("/health")
async def health():
    return {
        "status": "degraded" if app.state.warmup_errors else "ok",
        "mode": "safe_stubs",
        "warmup_errors": app.state.warmup_errors,
    }


@app.post("/triage", response_model=TriageResponse)
async def post_triage(req: TriageRequest) -> TriageResponse:
    return await triage(req)


@app.get("/metrics")
async def get_metrics():
    return metrics.snapshot()
